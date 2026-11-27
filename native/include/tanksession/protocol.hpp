#pragma once

#include "tanksession/analytics.hpp"
#include <iosfwd>

namespace tanksession {

inline constexpr std::size_t max_line_bytes = 256;

// Strict numeric ASCII protocol, version 1. No free text or identifiers cross
// the process boundary. Truncated, oversized and trailing input is rejected.
[[nodiscard]] std::expected<Report, Error> read_report(std::istream& input);
void write_json(std::ostream& output, const Report& report);

}  // namespace tanksession
