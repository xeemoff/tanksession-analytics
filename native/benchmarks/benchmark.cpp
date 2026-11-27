#include "tanksession/analytics.hpp"

#include <algorithm>
#include <charconv>
#include <chrono>
#include <iomanip>
#include <iostream>
#include <string_view>

int main(int argc, char** argv) {
    std::size_t count = 100'000;
    if (argc > 2) { return 2; }
    if (argc == 2) {
        const std::string_view argument(argv[1]);
        const auto parsed = std::from_chars(argument.data(), argument.data() + argument.size(), count);
        if (parsed.ec != std::errc{} || parsed.ptr != argument.data() + argument.size()) { return 2; }
    }
    if (count < 100 || count > tanksession::max_rows) { return 2; }
    std::vector<tanksession::Battle> rows;
    rows.reserve(count);
    for (std::size_t index = 0; index < count; ++index) {
        tanksession::Battle row;
        row.group = static_cast<std::uint32_t>(index % 32);
        row.outcome = static_cast<tanksession::Outcome>(index % 4);
        for (std::size_t field = 0; field < tanksession::metric_count; ++field) {
            if (index % 23 != field) {
                row.metrics[field] = static_cast<std::int64_t>((index * (13 + field)) % 7'000);
            }
        }
        rows.push_back(row);
    }
    std::vector<double> seconds;
    for (int iteration = 0; iteration < 4; ++iteration) {
        const auto start = std::chrono::steady_clock::now();
        const auto report = tanksession::analyze(rows, 32);
        const auto end = std::chrono::steady_clock::now();
        if (!report || report->overall.battles != count) { return 3; }
        if (iteration != 0) {
            seconds.push_back(std::chrono::duration<double>(end - start).count());
        }
    }
    std::sort(seconds.begin(), seconds.end());
    std::cout << std::setprecision(9)
              << "{\"scope\":\"native_core_only\",\"rows\":" << count
              << ",\"groups\":32,\"repeats\":3,\"median_seconds\":" << seconds[1]
              << ",\"min_seconds\":" << seconds[0] << "}\n";
    return 0;
}
