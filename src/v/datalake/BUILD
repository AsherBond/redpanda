load("//bazel:build.bzl", "redpanda_cc_library")

redpanda_cc_library(
    name = "conversion_outcome",
    srcs = [
    ],
    hdrs = [
        "conversion_outcome.h",
    ],
    include_prefix = "datalake",
    deps = [
        "//src/v/iceberg:values",
        "@seastar",
    ],
)

redpanda_cc_library(
    name = "protobuf_utils",
    srcs = [
        "protobuf_utils.cc",
    ],
    hdrs = [
        "protobuf_utils.h",
    ],
    include_prefix = "datalake",
    visibility = [":__subpackages__"],
    deps = [
        "@protobuf",
    ],
)

redpanda_cc_library(
    name = "schema_protobuf",
    srcs = [
        "schema_protobuf.cc",
    ],
    hdrs = [
        "schema_protobuf.h",
    ],
    include_prefix = "datalake",
    visibility = [":__subpackages__"],
    deps = [
        ":conversion_outcome",
        ":protobuf_utils",
        "//src/v/iceberg:datatypes",
        "@fmt",
        "@protobuf",
        "@seastar",
    ],
)

redpanda_cc_library(
    name = "logger",
    hdrs = [
        "logger.h",
    ],
    include_prefix = "datalake",
    visibility = [":__subpackages__"],
    deps = [
        "//src/v/base",
        "@seastar",
    ],
)

redpanda_cc_library(
    name = "partitioning_writer",
    srcs = [
        "partitioning_writer.cc",
    ],
    hdrs = [
        "partitioning_writer.h",
    ],
    implementation_deps = [
        ":logger",
        ":table_definition",
        "//src/v/base",
        "//src/v/iceberg:struct_accessor",
    ],
    include_prefix = "datalake",
    visibility = [":__subpackages__"],
    deps = [
        ":writer",
        "//src/v/container:chunked_hash_map",
        "//src/v/iceberg:datatypes",
        "//src/v/iceberg:partition_key",
        "//src/v/iceberg:values",
    ],
)

redpanda_cc_library(
    name = "types",
    hdrs = [
        "errors.h",
        "fwd.h",
    ],
    include_prefix = "datalake",
    visibility = ["//visibility:public"],
    deps = [
        "//src/v/base",
        "//src/v/serde",
    ],
)

redpanda_cc_library(
    name = "writer",
    srcs = [
        "data_writer_interface.cc",
    ],
    hdrs = [
        "data_writer_interface.h",
        "schemaless_translator.h",
    ],
    implementation_deps = [
        "@fmt",
    ],
    include_prefix = "datalake",
    visibility = [":__subpackages__"],
    deps = [
        ":base_types",
        ":table_definition",
        "//src/v/base",
        "//src/v/datalake/coordinator:data_file",
        "//src/v/iceberg:datatypes",
        "//src/v/iceberg:values",
        "//src/v/serde",
    ],
)

redpanda_cc_library(
    name = "manager",
    srcs = [
        "datalake_manager.cc",
    ],
    hdrs = [
        "datalake_manager.h",
    ],
    include_prefix = "datalake",
    visibility = ["//visibility:public"],
    deps = [
        ":logger",
        ":types",
        "//src/v/base",
        "//src/v/cluster",
        "//src/v/datalake/coordinator:frontend",
        "//src/v/model",
        "//src/v/raft",
        "//src/v/serde",
        "//src/v/ssx:semaphore",
        "@fmt",
        "@seastar",
    ],
)

redpanda_cc_library(
    name = "table_definition",
    srcs = [
        "table_definition.cc",
    ],
    hdrs = [
        "table_definition.h",
    ],
    implementation_deps = [
        "//src/v/iceberg:transform",
    ],
    include_prefix = "datalake",
    visibility = [":__subpackages__"],
    deps = [
        "//src/v/iceberg:partition",
        "//src/v/iceberg:schema",
    ],
)

redpanda_cc_library(
    name = "values_protobuf",
    srcs = [
        "values_protobuf.cc",
    ],
    hdrs = [
        "values_protobuf.h",
    ],
    include_prefix = "datalake",
    visibility = [":__subpackages__"],
    deps = [
        ":conversion_outcome",
        ":protobuf_utils",
        "//src/v/bytes:iobuf",
        "//src/v/container:fragmented_vector",
        "//src/v/iceberg:values",
        "//src/v/serde/protobuf",
        "//src/v/ssx:future_util",
        "@fmt",
        "@protobuf",
        "@seastar",
    ],
)

redpanda_cc_library(
    name = "base_types",
    srcs = [
        "base_types.cc",
    ],
    hdrs = [
        "base_types.h",
    ],
    include_prefix = "datalake",
    visibility = [":__subpackages__"],
    deps = [
        "//src/v/utils:named_type",
        "@fmt",
    ],
)

redpanda_cc_library(
    name = "cloud_data_io",
    srcs = [
        "cloud_data_io.cc",
    ],
    hdrs = [
        "cloud_data_io.h",
    ],
    include_prefix = "datalake",
    visibility = [":__subpackages__"],
    deps = [
        ":base_types",
        ":logger",
        "//src/v/base",
        "//src/v/cloud_io:remote",
        "//src/v/cloud_storage_clients",
        "//src/v/container:fragmented_vector",
        "//src/v/model",
        "//src/v/utils:lazy_abort_source",
        "//src/v/utils:named_type",
        "//src/v/utils:retry_chain_node",
        "//src/v/utils:stream_provider",
        "@fmt",
        "@seastar",
    ],
)
