#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <expected>
#include <optional>
#include <span>
#include <string_view>
#include <vector>

namespace tanksession {

inline constexpr std::size_t protocol_version = 1;
inline constexpr std::size_t max_rows = 1'000'000;
inline constexpr std::size_t max_groups = 4'096;
inline constexpr std::int64_t max_metric = 1'000'000'000'000;
inline constexpr std::size_t metric_count = 5;
inline constexpr std::array<std::string_view, metric_count> metric_names{
    "damage", "xp", "xp_base", "xp_bonus", "credits_net"};

enum class Outcome : std::uint8_t { unknown = 0, win = 1, loss = 2, draw = 3 };

struct Battle {
    std::uint32_t group{};
    Outcome outcome{Outcome::unknown};
    std::array<std::optional<std::int64_t>, metric_count> metrics{};
};

enum class ErrorCode {
    invalid_header, limits_exceeded, invalid_row, metric_out_of_range,
    truncated_input, trailing_input, missing_group, io_error
};

struct Error {
    ErrorCode code;
    std::size_t line{};
};

[[nodiscard]] std::string_view error_message(ErrorCode code);

struct MetricSummary {
    std::size_t known{};
    std::size_t missing{};
    std::optional<double> coverage_pct;
    std::optional<std::int64_t> sum;
    std::optional<double> mean;
    std::optional<double> sample_variance;
    std::optional<double> stddev;
    std::optional<double> p50;
    std::optional<double> p90;
    std::optional<double> coefficient_of_variation;
    std::optional<std::int64_t> minimum;
    std::optional<std::int64_t> maximum;
};

struct Summary {
    std::size_t battles{};
    std::size_t wins{};
    std::size_t losses{};
    std::size_t draws{};
    std::size_t outcomes_known{};
    std::optional<double> outcome_coverage_pct;
    std::optional<double> win_rate;
    std::array<MetricSummary, metric_count> metrics{};
};

struct Report {
    Summary overall;
    // Vector index is the dense, account-scoped group ID supplied by Python.
    std::vector<Summary> groups;
};

// Pure deterministic batch API; no journal, account, filesystem or game imports.
[[nodiscard]] std::expected<Report, Error> analyze(std::span<const Battle> rows,
                                                  std::size_t group_count);

}  // namespace tanksession
