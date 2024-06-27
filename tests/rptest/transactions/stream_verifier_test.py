# Copyright 2024 Redpanda Data, Inc.
#
# Use of this software is governed by the Business Source License
# included in the file licenses/BSL.md
#
# As of the Change Date specified in that file, in accordance with
# the Business Source License, use of this software will be governed
# by the Apache License, Version 2.0
import sys
import json

from rptest.services.cluster import cluster
from rptest.transactions.verifiers.stream_verifier import StreamVerifier

from rptest.tests.redpanda_test import RedpandaTest
from rptest.clients.types import TopicSpec
from rptest.util import inject_remote_script


class StreamVerifierTest(RedpandaTest):
    partition_count = 2
    topics = [TopicSpec(partition_count=partition_count, replication_factor=3)]

    def __init__(self, test_context):
        extra_rp_conf = {
            "id_allocator_replication": 3,
            "default_topic_replications": 3,
            "default_topic_partitions": 1
        }

        # basic topic info
        self.source_topic_prefix = "stream_topic_src"
        self.target_topic_prefix = "stream_topic_dst"

        self.default_topic_count = 1
        # per topic count is 1250
        self.default_message_count = 1250 * self.default_topic_count

        self.num_partitions = 1
        self.num_replicas = 3

        super(StreamVerifierTest, self).__init__(test_context=test_context,
                                                 extra_rp_conf=extra_rp_conf)

    def _try_parse_json(self, node, jsondata):
        try:
            return json.loads(jsondata)
        except ValueError:
            self.logger.debug(
                f"{str(node.account)}: Could not parse as json: {str(jsondata)}"
            )
            return None

    def _create_topics(self, brokers, node, topic_name_prefix, topic_count,
                       num_partitions, num_replicas):
        """Function uses batched topic creation approach.
        Its either single topic per request using ThreadPool in batches or
        the whole batch in single kafka request.

        Args:
            topic_count (int): Number of topics to create
            num_partitions (int): Number of partitions per topic
            num_replicas (int): Number of replicas per topic

        Raises:
            RuntimeError: Underlying creation script generated error

        Returns:
            list: topic names and timing data
        """
        # Prepare command
        remote_script_path = inject_remote_script(node, "topic_operations.py")
        cmd = f"python3 {remote_script_path} "
        cmd += f"--brokers '{brokers}' "
        cmd += f"--batch-size '32' "
        cmd += "create "
        cmd += f"--topic-prefix '{topic_name_prefix}' "
        cmd += f"--topic-count {topic_count} "
        cmd += "--kafka-batching "
        #cmd += f"--topic-name-length {topic_name_length} "
        cmd += f"--partitions {num_partitions} "
        cmd += f"--replicas {num_replicas} "
        cmd += "--skip-randomize-names"
        hostname = node.account.hostname
        self.logger.info(f"Starting topic creation script on '{hostname}")
        self.logger.debug(f"...cmd: {cmd}")

        data = {}
        for line in node.account.ssh_capture(cmd):
            # The script will produce jsons one, per line
            # And it will have timings only
            self.logger.debug(f"received {sys.getsizeof(line)}B "
                              f"from '{hostname}'.")
            data = self._try_parse_json(node, line.strip())
            if data is not None:
                if 'error' in data:
                    self.logger.warning(f"Node '{hostname}' reported "
                                        f"error:\n{data['error']}")
                    raise RuntimeError(data['error'])
            else:
                data = {}

        topic_details = data.get('topics', [])
        current_count = len(topic_details)
        self.logger.info(f"Created {current_count} topics")
        assert len(topic_details) == topic_count, \
            f"Topic count not reached: {current_count}/{topic_count}"

        return topic_details

    @cluster(num_nodes=4)
    def test_simple_produce_consume_txn(self):
        verifier = StreamVerifier(self.test_context, self.redpanda)
        verifier.start()

        # Source topics
        self._create_topics(self.redpanda.brokers(), verifier._node,
                            self.source_topic_prefix, self.default_topic_count,
                            self.num_partitions, self.num_replicas)
        # Target topics
        self._create_topics(self.redpanda.brokers(), verifier._node,
                            self.target_topic_prefix, self.default_topic_count,
                            self.num_partitions, self.num_replicas)

        # Update service config, see service module for details
        # Service parameters example:
        # service_conf = {
        #     "brokers": self._redpanda.brokers(),
        #     "topic_group_id": "group-stream-verifier-tx",
        #     "topic_prefix_produce": "stream-topic-dst",
        #     "topic_prefix_consume": "stream-topic-src",
        #     "topic_count": 16,
        #     "msg_rate_limit": 0,
        #     "msg_per_txn": 1,
        #     "msg_total": 256,
        #     "consume_stop_criteria": "sleep",
        #     "consume_timeout_s": 10,
        #     "consume_poll_timeout": 5,
        #     "consume_sleep_time_s": 60,
        #     "consumer_logging_threshold": 1000,
        #     "worker_threads": 4,
        # }

        # Consumer thread will work faster than any producer
        # If we start consume when produce it no finished yet
        # consumer will hit EOF earlier than produce finishes
        # sleep mode will wait for 'consume_sleep_time_s'
        # and check if new messages appeared
        verifier.update_service_config({
            "consume_stop_criteria": "sleep",
            "worker_threads": 1,
            "msg_per_txn": 1
        })
        # Produce
        verifier.remote_start_produce(self.source_topic_prefix,
                                      self.default_topic_count,
                                      self.default_message_count)
        self.logger.info("Waiting for 1000 produces messages")
        verifier.wait_for_processed_count('produce', 1000, 30)

        # Atomic
        self.logger.info("Produce action reached 1000 messages. "
                         "Starting to atomic consume/produce")
        verifier.remote_start_atomic(self.source_topic_prefix,
                                     self.target_topic_prefix, 1)
        verifier.wait_for_processed_count('atomic', 1000, 30)

        # Milestone check
        self.logger.info("Atomic action reached 1000 messages. "
                         "Waiting for produce to finish")
        verifier.remote_wait_action('produce')
        produce_status = verifier.remote_stop_produce()
        self.logger.info(
            f"Produce action finished:\n{json.dumps(produce_status, indent=2)}"
        )

        verifier.remote_wait_action('atomic')
        atomic_status = verifier.remote_stop_atomic()
        self.logger.info(
            f"Consume action finished:\n{json.dumps(atomic_status, indent=2)}")

        # Consume
        verifier.remote_start_consume(self.target_topic_prefix,
                                      self.default_topic_count)
        verifier.remote_wait_action('consume')
        consume_status = verifier.remote_stop_consume()
        self.logger.info(
            f"Consume action finished:\n{json.dumps(consume_status, indent=2)}"
        )

        produced_count = produce_status['stats']['processed_messages']
        atomic_count = atomic_status['stats']['processed_messages']
        consumed_count = consume_status['stats']['processed_messages']

        assert produced_count == atomic_count, \
            "Produced/Atomic message count mismatch"

        assert atomic_count == consumed_count, \
            "Atomic/Consumed message count mismatch"

        # TODO: Message content validation
