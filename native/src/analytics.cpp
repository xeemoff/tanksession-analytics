#include "tanksession/analytics.hpp"

#include <algorithm>
#include <cmath>
#include <ranges>

namespace tanksession {
namespace {

struct MetricAccumulator {
    std::vector<std::int64_t> values;
    std::int64_t sum{};
    std::int64_t origin{};
    double mean{};
    double m2{};

    void add(std::int64_t value) {
        if (values.empty()) { origin = value; }
        values.push_back(value);
        // Bounds guarantee abs(sum) <= 10^18, strictly inside int64_t.
        sum += value;
        // Center before converting to double: close values around 10^12 keep
        // their small dispersion instead of subtracting two rounded means.
        const auto centered = static_cast<double>(value - origin);
        const auto delta = centered - mean;
        mean += delta / static_cast<double>(values.size());
        m2 += delta * (centered - mean);
    }

    double quantile(double probability) const {
        const auto position = static_cast<double>(values.size() - 1) * probability;
        const auto lower = static_cast<std::size_t>(position);
        const auto upper = std::min(lower + 1, values.size() - 1);
        const auto fraction = position - static_cast<double>(lower);
        return static_cast<double>(values[lower]) + fraction *
            (static_cast<double>(values[upper]) - static_cast<double>(values[lower]));
    }

    MetricSummary finish(std::size_t battles, bool nonnegative) {
        MetricSummary result;
        result.known = values.size();
        result.missing = battles - result.known;
        if (battles != 0) {
            result.coverage_pct = 100.0 * static_cast<double>(result.known) /
                                  static_cast<double>(battles);
        }
        if (values.empty()) {
            return result;
        }
        result.sum = sum;
        const auto actual_mean = static_cast<double>(origin) + mean;
        result.mean = actual_mean;
        if (values.size() >= 2) {
            result.sample_variance = std::max(0.0, m2) / static_cast<double>(values.size() - 1);
            result.stddev = std::sqrt(*result.sample_variance);
            if (nonnegative && actual_mean > 0.0) {
                result.coefficient_of_variation = *result.stddev / actual_mean;
            }
        }
        std::ranges::sort(values);
        result.minimum = values.front();
        result.maximum = values.back();
        result.p50 = quantile(0.5);
        result.p90 = quantile(0.9);
        return result;
    }
};

struct Accumulator {
    std::size_t battles{};
    std::array<std::size_t, 4> outcomes{};
    std::array<MetricAccumulator, metric_count> metrics;

    void add(const Battle& row) {
        ++battles;
        ++outcomes[static_cast<std::size_t>(row.outcome)];
        for (std::size_t index = 0; index < metric_count; ++index) {
            if (row.metrics[index].has_value()) {
                metrics[index].add(*row.metrics[index]);
            }
        }
    }

    Summary finish() {
        Summary result;
        result.battles = battles;
        result.wins = outcomes[1];
        result.losses = outcomes[2];
        result.draws = outcomes[3];
        result.outcomes_known = battles - outcomes[0];
        if (battles != 0) {
            result.outcome_coverage_pct = 100.0 * static_cast<double>(result.outcomes_known) /
                                          static_cast<double>(battles);
        }
        if (result.outcomes_known != 0) {
            result.win_rate = 100.0 * static_cast<double>(result.wins) /
                              static_cast<double>(result.outcomes_known);
        }
        for (std::size_t index = 0; index < metric_count; ++index) {
            result.metrics[index] = metrics[index].finish(battles, index != metric_count - 1);
        }
        return result;
    }
};

}  // namespace

std::string_view error_message(ErrorCode code) {
    switch (code) {
    case ErrorCode::invalid_header: return "invalid protocol header";
    case ErrorCode::limits_exceeded: return "input limit exceeded";
    case ErrorCode::invalid_row: return "invalid numeric row";
    case ErrorCode::metric_out_of_range: return "metric outside companion range";
    case ErrorCode::truncated_input: return "truncated input";
    case ErrorCode::trailing_input: return "unexpected trailing input";
    case ErrorCode::missing_group: return "declared group has no rows";
    case ErrorCode::io_error: return "input read failed";
    }
    return "unknown input error";
}

std::expected<Report, Error> analyze(std::span<const Battle> rows, std::size_t group_count) {
    if (rows.size() > max_rows || group_count > max_groups || group_count > rows.size() ||
        (rows.empty() != (group_count == 0))) {
        return std::unexpected(Error{ErrorCode::limits_exceeded});
    }
    Accumulator overall;
    std::vector<Accumulator> groups(group_count);
    for (std::size_t position = 0; position < rows.size(); ++position) {
        const auto& row = rows[position];
        if (row.group >= group_count || static_cast<std::size_t>(row.outcome) > 3) {
            return std::unexpected(Error{ErrorCode::invalid_row, position + 2});
        }
        for (std::size_t index = 0; index < metric_count; ++index) {
            const auto value = row.metrics[index];
            if (value && (*value < -max_metric || *value > max_metric ||
                          (index != metric_count - 1 && *value < 0))) {
                return std::unexpected(Error{ErrorCode::metric_out_of_range, position + 2});
            }
        }
        overall.add(row);
        groups[row.group].add(row);
    }
    Report report;
    report.groups.reserve(group_count);
    for (auto& group : groups) {
        if (group.battles == 0) {
            return std::unexpected(Error{ErrorCode::missing_group});
        }
        report.groups.push_back(group.finish());
    }
    report.overall = overall.finish();
    return report;
}

}  // namespace tanksession
