/*
 * Copyright 2024 Redpanda Data, Inc.
 *
 * Licensed as a Redpanda Enterprise file under the Redpanda Community
 * License (the "License"); you may not use this file except in compliance with
 * the License. You may obtain a copy of the License at
 *
 * https://github.com/redpanda-data/redpanda/blob/master/licenses/rcl.md
 */

#pragma once

#include "base/outcome.h"
#include "cloud_storage/inventory/types.h"
#include "cloud_storage_clients/types.h"
#include "model/fundamental.h"

namespace cloud_storage::inventory {

/// \brief AWS specific inventory API calls
class aws_ops final : public base_ops {
public:
    aws_ops(
      cloud_storage_clients::bucket_name bucket,
      inventory_config_id inventory_config_id,
      ss::sstring inventory_prefix);

    ss::future<cloud_storage::upload_result> create_inventory_configuration(
      cloud_storage::cloud_storage_api&,
      retry_chain_node&,
      report_generation_frequency,
      report_format) override;

    ss::future<bool> inventory_configuration_exists(
      cloud_storage::cloud_storage_api&, retry_chain_node&) override;

    /// Returns metadata for the latest available report for
    /// inventory configuration assigned to this object
    ss::future<result<report_metadata, error_outcome>>
    fetch_latest_report_metadata(
      cloud_storage::cloud_storage_api&,
      retry_chain_node&) const noexcept override;

private:
    ss::future<result<report_metadata, error_outcome>>
    do_fetch_latest_report_metadata(
      cloud_storage::cloud_storage_api&, retry_chain_node&) const;

    /// Fetches the report manifest and parses out report paths from the JSON
    /// document
    ss::future<result<report_paths, error_outcome>> fetch_and_parse_metadata(
      cloud_storage::cloud_storage_api& remote,
      retry_chain_node& parent_rtc,
      cloud_storage_clients::object_key metadata_path) const noexcept;

    ss::future<result<report_paths, error_outcome>> do_fetch_and_parse_metadata(
      cloud_storage::cloud_storage_api& remote,
      retry_chain_node& parent_rtc,
      cloud_storage_clients::object_key metadata_path) const;

    result<report_paths, error_outcome>
    parse_report_paths(iobuf json_response) const;

    cloud_storage_clients::bucket_name _bucket;
    inventory_config_id _inventory_config_id;
    cloud_storage_clients::object_key _inventory_key;
    ss::sstring _prefix;
};

} // namespace cloud_storage::inventory
