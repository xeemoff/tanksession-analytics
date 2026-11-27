#include "tanksession/protocol.hpp"

#include <exception>
#include <cstdio>
#include <iostream>
#include <string_view>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

int main(int argc, char** argv) {
    if (argc == 2 && std::string_view(argv[1]) == "--version") {
        std::cout << "tanksession-native protocol 1\n";
        return 0;
    }
    if (argc == 2 && std::string_view(argv[1]) == "--help") {
        std::cout << "Usage: tanksession-native < validated-input.tsv\n"
                     "Use tools/native_report.py to read an account-scoped journal.\n"
                     "Input: TSA_NATIVE<TAB>1<TAB>rows<TAB>groups, then numeric rows.\n"
                     "Output: one protocol-1 JSON report. No files are modified.\n";
        return 0;
    }
    if (argc != 1) {
        std::cerr << "native report: unsupported arguments\n";
        return 2;
    }
#ifdef _WIN32
    // CRT text mode interprets Ctrl-Z as EOF. Treat the protocol as bytes on
    // Windows too, so a trailing payload cannot be hidden behind that byte.
    if (_setmode(_fileno(stdin), _O_BINARY) == -1 ||
        _setmode(_fileno(stdout), _O_BINARY) == -1) {
        std::cerr << "native report: binary stream setup failed\n";
        return 3;
    }
#endif
    try {
        auto result = tanksession::read_report(std::cin);
        if (!result) {
            std::cerr << "native report: " << tanksession::error_message(result.error().code)
                      << " (line " << result.error().line << ")\n";
            return 2;
        }
        tanksession::write_json(std::cout, *result);
        if (!std::cout) {
            std::cerr << "native report: output write failed\n";
            return 3;
        }
        return 0;
    } catch (const std::exception&) {
        // Never print raw input or allocator/library exception details.
        std::cerr << "native report: computation failed\n";
        return 3;
    }
}
