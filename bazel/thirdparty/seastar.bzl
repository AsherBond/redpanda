load("//bazel:build.bzl", "redpanda_cc_library")

def seastar_cc_swagger_library(name, src, definitions = [], visibility = None):
    hh_out = src + ".hh"
    cc_out = src + ".cc"
    src_abs = "$(location " + src + ")"
    hh_out_abs = "$(location " + hh_out + ")"

    native.genrule(
        name = name + "_genrule",
        srcs = [src] + definitions,
        outs = [hh_out, cc_out],
        cmd = "$(location @seastar//:seastar-json2code) --create-cc -f " + src_abs + " -o " + hh_out_abs,
        tools = ["@seastar//:seastar-json2code"],
    )

    redpanda_cc_library(
        name = name,
        srcs = [
            cc_out,
        ],
        visibility = visibility,
        hdrs = [
            hh_out,
        ],
        deps = [
            "@seastar",
        ],
    )