#include "tanksession/protocol.hpp"

#include <charconv>
#include <iomanip>
#include <istream>
#include <locale>
#include <ostream>
#include <string>
#include <system_error>

namespace tanksession {
namespace {

std::expected<std::optional<std::string>, Error> read_line(std::istream& input, std::size_t number) {
    std::string line;
    line.reserve(max_line_bytes);
    char character{};
    while (input.get(character)) {
        if (character == '\n') {
            if (!line.empty() && line.back() == '\r') {
                line.pop_back();
            }
            return line;
        }
        if (line.size() == max_line_bytes) {
            return std::unexpected(Error{ErrorCode::limits_exceeded, number});
        }
        line.push_back(character);
    }
    if (input.bad() || (input.fail() && !input.eof())) {
        return std::unexpected(Error{ErrorCode::io_error, number});
    }
    if (!line.empty()) {
        return std::unexpected(Error{ErrorCode::truncated_input, number});
    }
    return std::nullopt;
}

template <std::size_t Count>
std::optional<std::array<std::string_view, Count>> split(std::string_view line) {
    std::array<std::string_view, Count> fields;
    for (std::size_t index = 0; index < Count; ++index) {
        const auto end = line.find('\t');
        if ((index + 1 < Count) == (end == std::string_view::npos)) {
            return std::nullopt;
        }
        fields[index] = line.substr(0, end);
        if (fields[index].empty()) {
            return std::nullopt;
        }
        if (end != std::string_view::npos) {
            line.remove_prefix(end + 1);
        }
    }
    return fields;
}

std::optional<std::int64_t> integer(std::string_view token) {
    if (token.empty() || token.front() == '+' || token == "-0" ||
        (token.size() > 1 && token.front() == '0') ||
        (token.size() > 2 && token.starts_with("-0"))) {
        return std::nullopt;
    }
    std::int64_t result{};
    const auto conversion = std::from_chars(token.data(), token.data() + token.size(), result);
    if (conversion.ec != std::errc{} || conversion.ptr != token.data() + token.size()) {
        return std::nullopt;
    }
    return result;
}

template <typename T>
void optional_number(std::ostream& output, const std::optional<T>& value) {
    if (value) {
        output << *value;
    } else {
        output << "null";
    }
}

void metric_json(std::ostream& output, const MetricSummary& metric) {
    output << "{\"known\":" << metric.known << ",\"missing\":" << metric.missing;
    output << ",\"coverage_pct\":";
    optional_number(output, metric.coverage_pct);
    output << ",\"sum\":";
    if (metric.sum) {
        // Exact decimal text remains exact in JavaScript and Python alike.
        output << '"' << *metric.sum << '"';
    } else {
        output << "null";
    }
    output << ",\"mean\":"; optional_number(output, metric.mean);
    output << ",\"sample_variance\":"; optional_number(output, metric.sample_variance);
    output << ",\"stddev\":"; optional_number(output, metric.stddev);
    output << ",\"p50\":"; optional_number(output, metric.p50);
    output << ",\"p90\":"; optional_number(output, metric.p90);
    output << ",\"coefficient_of_variation\":"; optional_number(output, metric.coefficient_of_variation);
    output << ",\"min\":"; optional_number(output, metric.minimum);
    output << ",\"max\":"; optional_number(output, metric.maximum);
    output << '}';
}

void summary_json(std::ostream& output, const Summary& summary) {
    output << "{\"battles\":" << summary.battles << ",\"wins\":" << summary.wins;
    output << ",\"losses\":" << summary.losses << ",\"draws\":" << summary.draws;
    output << ",\"outcomes_known\":" << summary.outcomes_known << ",\"outcome_coverage_pct\":";
    optional_number(output, summary.outcome_coverage_pct);
    output << ",\"win_rate\":"; optional_number(output, summary.win_rate);
    output << ",\"metrics\":{";
    for (std::size_t index = 0; index < metric_count; ++index) {
        if (index != 0) { output << ','; }
        output << '"' << metric_names[index] << "\":";
        metric_json(output, summary.metrics[index]);
    }
    output << "}}";
}

}  // namespace

std::expected<Report, Error> read_report(std::istream& input) {
    auto header = read_line(input, 1);
    if (!header) { return std::unexpected(header.error()); }
    if (!*header) { return std::unexpected(Error{ErrorCode::truncated_input, 1}); }
    const auto fields = split<4>(**header);
    if (!fields || (*fields)[0] != "TSA_NATIVE" || (*fields)[1] != "1") {
        return std::unexpected(Error{ErrorCode::invalid_header, 1});
    }
    const auto count = integer((*fields)[2]);
    const auto groups = integer((*fields)[3]);
    if (!count || !groups || *count < 0 || *groups < 0 ||
        *count > static_cast<std::int64_t>(max_rows) ||
        *groups > static_cast<std::int64_t>(max_groups) || *groups > *count ||
        ((*count == 0) != (*groups == 0))) {
        return std::unexpected(Error{ErrorCode::limits_exceeded, 1});
    }
    std::vector<Battle> rows;
    rows.reserve(static_cast<std::size_t>(*count));
    for (std::int64_t position = 0; position < *count; ++position) {
        const auto line_number = static_cast<std::size_t>(position) + 2;
        auto line = read_line(input, line_number);
        if (!line) { return std::unexpected(line.error()); }
        if (!*line) { return std::unexpected(Error{ErrorCode::truncated_input, line_number}); }
        const auto columns = split<metric_count + 2>(**line);
        if (!columns) { return std::unexpected(Error{ErrorCode::invalid_row, line_number}); }
        const auto group = integer((*columns)[0]);
        const auto outcome = integer((*columns)[1]);
        if (!group || !outcome || *group < 0 || *group >= *groups || *outcome < 0 || *outcome > 3) {
            return std::unexpected(Error{ErrorCode::invalid_row, line_number});
        }
        Battle row;
        row.group = static_cast<std::uint32_t>(*group);
        row.outcome = static_cast<Outcome>(*outcome);
        for (std::size_t index = 0; index < metric_count; ++index) {
            const auto token = (*columns)[index + 2];
            if (token != "?") {
                const auto value = integer(token);
                if (!value) { return std::unexpected(Error{ErrorCode::invalid_row, line_number}); }
                if (*value < -max_metric || *value > max_metric ||
                    (index != metric_count - 1 && *value < 0)) {
                    return std::unexpected(Error{ErrorCode::metric_out_of_range, line_number});
                }
                row.metrics[index] = *value;
            }
        }
        rows.push_back(row);
    }
    auto trailing = read_line(input, static_cast<std::size_t>(*count) + 2);
    if (!trailing) { return std::unexpected(trailing.error()); }
    if (*trailing) { return std::unexpected(Error{ErrorCode::trailing_input, static_cast<std::size_t>(*count) + 2}); }
    return analyze(rows, static_cast<std::size_t>(*groups));
}

void write_json(std::ostream& output, const Report& report) {
    output.imbue(std::locale::classic());
    output << std::setprecision(17);
    output << "{\"protocol\":1,\"definitions\":{\"variance\":\"sample\","
              "\"quantile\":\"linear_r7\",\"win_rate\":\"wins/known_outcomes\","
              "\"sum\":\"exact_decimal_string\"},\"overall\":";
    summary_json(output, report.overall);
    output << ",\"groups\":[";
    for (std::size_t index = 0; index < report.groups.size(); ++index) {
        if (index != 0) { output << ','; }
        output << "{\"id\":" << index << ",\"statistics\":";
        summary_json(output, report.groups[index]);
        output << '}';
    }
    output << "]}\n";
}

}  // namespace tanksession
