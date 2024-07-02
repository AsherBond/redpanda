# Copyright 2024 Redpanda Data, Inc.
#
# Use of this software is governed by the Business Source License
# included in the file licenses/BSL.md
#
# As of the Change Date specified in that file, in accordance with
# the Business Source License, use of this software will be governed
# by the Apache License, Version 2.0
import json
import random
import numpy
import sys

from ducktape.utils.util import wait_until
from rptest.services.admin import Admin
from rptest.services.cluster import cluster
from rptest.services.redpanda import RESTART_LOG_ALLOW_LIST, MetricsEndpoint
from rptest.services.redpanda_installer import RedpandaInstaller
from rptest.transactions.verifiers.stream_verifier import StreamVerifier
from rptest.tests.redpanda_test import RedpandaTest
from rptest.util import inject_remote_script


class StreamVerifierTest(RedpandaTest):
    # Max time to wait for the cluster to be healthy once more.
    HEALTHY_WAIT_SECONDS = 20 * 60

    # Up to 5 min to stop the node with a lot of topics
    STOP_TIMEOUT = 60 * 5

    def __init__(self, test_context):
        # basic topic info
        self.source_topic_prefix = "stream_topic_src"
        self.target_topic_prefix = "stream_topic_dst"

        self.default_topic_count = 1
        # per topic count is 1250
        self.default_message_count = 1250 * self.default_topic_count

        self.num_partitions = 1
        self.num_replicas = 3

        # 2 messages per second for lifecycle tests
        self.msg_rate_limit = 2
        # Progress check normal interval of 5 seconds
        self.progress_check_seconds = 5
        # Message count for progress check
        self.progress_check_msg_count = \
            self.progress_check_seconds * self.msg_rate_limit

        # Triple time for timeoout
        self.progress_check_timeout = self.progress_check_seconds * 3
        # Save context for future use
        self.test_context = test_context

        extra_rp_conf = {
            "id_allocator_replication": 3,
            "default_topic_replications": 3,
            "default_topic_partitions": 1
        }
        # 3 brokers active, 1 standby
        super(StreamVerifierTest, self).__init__(num_brokers=4,
                                                 test_context=test_context,
                                                 extra_rp_conf=extra_rp_conf)

        self.admin = Admin(self.redpanda)
        self.installer = self.redpanda._installer

    def setUp(self):
        # start the nodes manually
        pass

    def _start_initial_broker_set(self):
        seed_nodes = self.redpanda.nodes[0:-1]
        self._standby_broker = self.redpanda.nodes[-1]

        self.redpanda.set_seed_servers(seed_nodes)
        self.redpanda.start(nodes=seed_nodes, omit_seeds_on_idx_one=False)

    def _try_parse_json(self, node, jsondata):
        try:
            return json.loads(jsondata)
        except ValueError:
            self.logger.debug(f"{str(node.account)}: "
                              f"Could not parse as json: {str(jsondata)}")
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
        cmd += "--batch-size '32' "
        cmd += "create "
        cmd += f"--topic-prefix '{topic_name_prefix}' "
        cmd += f"--topic-count {topic_count} "
        cmd += "--kafka-batching "
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

    def create_topics(self):
        # Source topics
        self._create_topics(self.redpanda.brokers(), self.verifier._node,
                            self.source_topic_prefix, self.default_topic_count,
                            self.num_partitions, self.num_replicas)
        # Target topics
        self._create_topics(self.redpanda.brokers(), self.verifier._node,
                            self.target_topic_prefix, self.default_topic_count,
                            self.num_partitions, self.num_replicas)

    def start_producer(self, wait_msg_count=50):
        self.verifier.remote_start_produce(self.source_topic_prefix,
                                           self.default_topic_count,
                                           self.default_message_count)
        self.logger.info(f"Waiting for {wait_msg_count} produces messages")
        self.verifier.wait_for_processed_count('produce', wait_msg_count, 30)
        self.logger.info(f"Produce action reached {wait_msg_count} messages.")

    def start_atomic(self, wait_msg_count=50):
        self.verifier.remote_start_atomic(self.source_topic_prefix,
                                          self.target_topic_prefix, 1)
        self.verifier.wait_for_processed_count('atomic', wait_msg_count, 30)

        # Milestone check
        self.logger.info(f"Atomic action reached {wait_msg_count} messages. ")

    def run_consumer(self):
        self.verifier.remote_start_consume(self.target_topic_prefix,
                                           self.default_topic_count)
        self.verifier.remote_wait_action('consume')
        consume_status = self.verifier.remote_stop_consume()
        self.logger.info(
            f"Consume action finished:\n{json.dumps(consume_status, indent=2)}"
        )

    def verify(self):
        produce_status = self.verifier.get_produce_status()
        atomic_status = self.verifier.get_atomic_status()
        consume_status = self.verifier.get_consume_status()
        produced_count = produce_status['stats']['processed_messages']
        atomic_count = atomic_status['stats']['processed_messages']
        consumed_count = consume_status['stats']['processed_messages']

        assert produced_count == atomic_count, \
            "Produced/Atomic message count mismatch: " \
            f"{produced_count}/{atomic_count}"

        assert atomic_count == consumed_count, \
            "Atomic/Consumed message count mismatch: " \
            f"{atomic_count}/{consumed_count}"

        errors = "\n".join(consume_status['errors'])
        assert len(consume_status['errors']) < 1, \
            f"Consume action has validation errors:\n{errors}"

    @cluster(num_nodes=5, log_allow_list=RESTART_LOG_ALLOW_LIST)
    def test_simple_produce_consume_txn(self):
        self._start_initial_broker_set()

        self.verifier = StreamVerifier(self.test_context, self.redpanda)
        self.verifier.start()

        self.create_topics()

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
        self.verifier.update_service_config({
            "consume_stop_criteria": "sleep",
            "consume_sleep_time_s": 30,
            "worker_threads": 1,
            "msg_per_txn": 1
        })
        # Produce
        self.logger.info("Starting producer")
        self.start_producer(wait_msg_count=500)

        # Atomic
        self.logger.info("Starting to atomic consume/produce")
        self.start_atomic(wait_msg_count=500)

        # Milestone check
        self.logger.info("Waiting for produce to finish")
        self.verifier.remote_wait_action('produce')

        produce_status = self.verifier.remote_stop_produce()
        self.logger.info(
            f"Produce action finished:\n{json.dumps(produce_status, indent=2)}"
        )

        self.verifier.remote_wait_action('atomic')
        atomic_status = self.verifier.remote_stop_atomic()
        self.logger.info(
            f"Atomic action finished:\n{json.dumps(atomic_status, indent=2)}")

        # Consume
        self.run_consumer()
        self.verify()

    def _get_partition_count(self):
        return self.redpanda.metric_sum(
            'redpanda_cluster_partitions',
            metrics_endpoint=MetricsEndpoint.PUBLIC_METRICS,
            nodes=self.redpanda.started_nodes())

    def _wait_until_cluster_healthy(self, include_underreplicated=True):
        """
        Waits until the cluster is reporting no under-replicated
        or leaderless partitions.
        """
        def is_healthy():
            unavailable_count = self.redpanda.metric_sum(
                'redpanda_cluster_unavailable_partitions',
                metrics_endpoint=MetricsEndpoint.PUBLIC_METRICS,
                nodes=self.redpanda.started_nodes())
            under_replicated_count = self.redpanda.metric_sum(
                'vectorized_cluster_partition_under_replicated_replicas',
                nodes=self.redpanda.started_nodes())
            self.logger.info(
                f"under-replicated partitions count: {under_replicated_count} "
                f"unavailable_count: {unavailable_count}")
            return unavailable_count == 0 and \
                (under_replicated_count == 0 or not include_underreplicated)

        wait_until(
            lambda: is_healthy(),
            timeout_sec=self.HEALTHY_WAIT_SECONDS,
            backoff_sec=30,
            err_msg=f"couldn't reach under-replicated count target: {0}")

    def _select_random_node(self):
        ids = [self.redpanda.node_id(n) for n in self.redpanda.started_nodes()]
        return self.redpanda.get_node_by_id(random.choice(ids))

    def _wait_for_leadership_stabilized(self, maintenance_node):
        def is_stabilized(threshold=0.1):
            leaders_per_node = [
                self.redpanda.metric_sum('vectorized_cluster_partition_leader',
                                         nodes=[n]) for n in nodes
            ]
            stddev = numpy.std(leaders_per_node)
            error = stddev / (self._get_partition_count() / len(nodes))
            self.logger.info(f"leadership info (stddev: {stddev:.2f}; "
                             f"want error {error:.2f} < {threshold})")

            return error < threshold

        # get nodes w/o maintenance one
        nodes = [
            n for n in self.redpanda.started_nodes() if n != maintenance_node
        ]
        wait_until(is_stabilized,
                   timeout_sec=self.HEALTHY_WAIT_SECONDS,
                   backoff_sec=30)

        return

    def _wait_for_leadership_balanced(self):
        def is_balanced(threshold=0.1):
            leaders_per_node = [
                self.redpanda.metric_sum('vectorized_cluster_partition_leader',
                                         nodes=[n])
                for n in self.redpanda.started_nodes()
            ]
            stddev = numpy.std(leaders_per_node)
            error = stddev / (self._get_partition_count() /
                              len(self.redpanda.started_nodes()))
            self.logger.info(f"leadership info (stddev: {stddev:.2f}; "
                             f"want error {error:.2f} < {threshold})")

            return error < threshold

        wait_until(is_balanced,
                   timeout_sec=self.HEALTHY_WAIT_SECONDS,
                   backoff_sec=30)

    def _in_maintenance_mode(self, node):
        status = self.admin.maintenance_status(node)
        return status["draining"]

    def _enable_maintenance_mode(self, node):
        self.admin.maintenance_start(node)
        wait_until(lambda: self._in_maintenance_mode(node),
                   timeout_sec=30,
                   backoff_sec=5)

        def has_drained_leadership():
            status = self.admin.maintenance_status(node)
            self.logger.debug(f"Maintenance status for {node.name}: {status}")
            if all([
                    key in status
                    for key in ['finished', 'errors', 'partitions']
            ]):
                return status["finished"] and not status["errors"] and \
                        status["partitions"] > 0
            else:
                return False

        self.logger.debug(f"Waiting for node {node.name} leadership to drain")
        wait_until(has_drained_leadership,
                   timeout_sec=self.HEALTHY_WAIT_SECONDS,
                   backoff_sec=30)

    def _disable_maintenance_mode(self, node):
        self.admin.maintenance_stop(node)

        wait_until(lambda: not self._in_maintenance_mode(node),
                   timeout_sec=self.HEALTHY_WAIT_SECONDS,
                   backoff_sec=10)

    def _streaming_test_flow(self, test):
        """Main lifecycle test flow

        Args:
            test (Callable): Check that about to happen
                             while message being processed
        """
        self._start_initial_broker_set()

        # Do the healthcheck on RP
        # to make sure that all topics are settle down and have their leader
        self._wait_until_cluster_healthy()

        # Prepare stream verifier
        self.verifier.update_service_config({
            "consume_stop_criteria":
            "sleep",
            "consume_sleep_time_s":
            30,
            "worker_threads":
            1,
            "msg_per_txn":
            1,
            # 2 messages per sec out of 1250 total will be ~10 min
            "msg_rate_limit":
            self.msg_rate_limit
        })

        self.create_topics()

        # Produce
        self.logger.info("Starting producer")
        self.start_producer(wait_msg_count=50)

        # Atomic
        self.logger.info("Starting to atomic consume/produce")
        self.start_atomic(wait_msg_count=50)

        # Start lifecycle test
        self.logger.info("Starting lifecycle test")
        test()
        self._wait_until_cluster_healthy()
        self.logger.info("Finished lifecycle test")

        # make sure that atomic action is finished
        self.verifier.remote_wait_action("atomic")

        # Consume and check
        self.run_consumer()
        self.verify()

    def _test_restart_safely(self):
        # Put node in maintenance
        maintenance_node = self._select_random_node()
        self.logger.info("Selected maintenance node is "
                         f"'{maintenance_node.account.hostname}'")
        self._enable_maintenance_mode(maintenance_node)

        # Wait for healthy status
        self.logger.info("Waiting for leadership stabilization ")
        self._wait_for_leadership_stabilized(maintenance_node)
        self._wait_until_cluster_healthy()

        # Check workload progress
        self.logger.info("Waiting for progress on atomic action")
        self.verifier.ensure_progress('atomic', self.progress_check_msg_count,
                                      self.progress_check_timeout)

        # Stop node in maintenance
        self.logger.info("Stopping maintenance node of "
                         f"'{maintenance_node.account.hostname}'")
        self.redpanda.stop_node(maintenance_node, timeout=self.STOP_TIMEOUT)

        # Again, wait for healthy cluster
        # This time underreplicated partion count should spike, ignore that
        # until restart
        self.logger.info("Making sure that cluster is healthy")
        self._wait_until_cluster_healthy(include_underreplicated=False)

        # Check workload progress
        self.logger.info("Waiting for progress on atomic action")
        self.verifier.ensure_progress('atomic', self.progress_check_msg_count,
                                      self.progress_check_timeout)

        # Restart node
        self.logger.info("Starting maintenance node of "
                         f"'{maintenance_node.account.hostname}'")
        self.redpanda.start_node(maintenance_node)
        self.logger.info("Disabling maintenance on node "
                         f"'{maintenance_node.account.hostname}'")
        self._disable_maintenance_mode(maintenance_node)

    def _restart_unsafely(self):
        # Stop node in maintenance
        maintenance_node = self._select_random_node()
        self.logger.info("Selected node for hard stop is "
                         f"'{maintenance_node.account.hostname}'")
        self.redpanda.stop_node(maintenance_node,
                                timeout=self.STOP_TIMEOUT,
                                forced=True)

        # Again, wait for healthy cluster
        # There will be underreplicated partitions spike, ignore it
        self.logger.info("Making sure that cluster is healthy")
        self._wait_until_cluster_healthy(include_underreplicated=False)

        # Check workload progress
        self.logger.info("Waiting for progress on atomic action")
        self.verifier.ensure_progress('atomic', self.progress_check_msg_count,
                                      self.progress_check_timeout)

        # Restart node
        self.redpanda.start_node(maintenance_node)
        self.logger.info("Disabling maintenance on node "
                         f"'{maintenance_node.account.hostname}'")
        self._disable_maintenance_mode(maintenance_node)

        # Check workload progress
        self.logger.info("Waiting for progress on atomic action")
        self.verifier.ensure_progress('atomic', self.progress_check_msg_count,
                                      self.progress_check_timeout)

    def _test_upgrade_cluster(self):
        # Save current version
        current_version = self.redpanda.get_version_int_tuple(
            self.redpanda.nodes[0])

        # Downgrade cluster
        self.old_version = \
            self.redpanda._installer.highest_from_prior_feature_version(
                RedpandaInstaller.HEAD)
        self.old_version_str = f"v{self.old_version[0]}.{self.old_version[1]}.{self.old_version[2]}"
        self.installer.install(self.redpanda.nodes, self.old_version)
        self.redpanda.restart_nodes(self.redpanda.started_nodes)

        self._wait_until_cluster_healthy(include_underreplicated=False)

        # Check workload progress
        self.logger.info("Waiting for progress on atomic action")
        self.verifier.ensure_progress('atomic', self.progress_check_msg_count,
                                      self.progress_check_timeout)

        # Upgrade cluster
        self.installer.install(self.redpanda.nodes, current_version)
        self.redpanda.restart_nodes(self.redpanda.started_nodes)

        self._wait_until_cluster_healthy(include_underreplicated=False)
        return

    @cluster(num_nodes=5, log_allow_list=RESTART_LOG_ALLOW_LIST)
    def test_streaming_restart_safely(self):
        self._start_initial_broker_set()

        self.verifier = StreamVerifier(self.test_context, self.redpanda)
        self.verifier.start()

        self._streaming_test_flow(self._test_restart_safely)

    @cluster(num_nodes=5, log_allow_list=RESTART_LOG_ALLOW_LIST)
    def test_streaming_upgrade(self):
        self._start_initial_broker_set()

        self.verifier = StreamVerifier(self.test_context, self.redpanda)
        self.verifier.start()

        self._streaming_test_flow(self._test_upgrade_cluster)
