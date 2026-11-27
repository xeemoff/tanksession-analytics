#include "tanksession/protocol.hpp"
#include <gtest/gtest.h>
#include <sstream>
#include <string>

namespace {
using namespace tanksession;

auto parse(const std::string& text) {
    std::istringstream input(text);
    return read_report(input);
}

TEST(Protocol, AcceptsEmptyAndNormalInputWithLfOrCrLf) {
    EXPECT_TRUE(parse("TSA_NATIVE\t1\t0\t0\n"));
    const auto result = parse("TSA_NATIVE\t1\t1\t1\r\n0\t1\t0\t500\t200\t300\t-10\r\n");
    ASSERT_TRUE(result);
    EXPECT_EQ(*result->overall.metrics[4].sum, -10);
    EXPECT_EQ(*result->overall.metrics[2].sum, 200);
}

TEST(Protocol, RejectsUnknownVersionAndMalformedCounts) {
    for (const auto* text : {"TSA_NATIVE\t2\t0\t0\n", "TSA_NATIVE\t1\t1\n",
                            "TSA_NATIVE\t1\t1000001\t1\n", "TSA_NATIVE\t1\t1\t4097\n",
                            "TSA_NATIVE\t1\t-1\t0\n", "TSA_NATIVE\t1\t01\t1\n",
                            "TSA_NATIVE\t1\t0\t1\n", "TSA_NATIVE\t1\t1\t0\n"}) {
        EXPECT_FALSE(parse(text)) << text;
    }
}

TEST(Protocol, RejectsTruncationAndTrailingRowsRatherThanPartialOutput) {
    for (const auto* text : {"", "TSA_NATIVE\t1\t0\t0", "TSA_NATIVE\t1\t1\t1\n",
                            "TSA_NATIVE\t1\t1\t1\n0\t0\t?\t?\t?\t?\t?",
                            "TSA_NATIVE\t1\t0\t0\n\n", "TSA_NATIVE\t1\t0\t0\nextra\n"}) {
        EXPECT_FALSE(parse(text));
    }
}

TEST(Protocol, RejectsNonCanonicalNumbersAndNonAsciiWithoutCoercion) {
    for (const auto* value : {"null", "nan", "1.0", "1e2", "+1", "01", "-0", " 1",
                             "1 ", "999999999999999999999999", "\xD9\xA1", "-1"}) {
        const auto text = std::string("TSA_NATIVE\t1\t1\t1\n0\t1\t") + value + "\t?\t?\t?\t?\n";
        EXPECT_FALSE(parse(text)) << value;
    }
}

TEST(Protocol, MissingAndZeroRemainDifferentInJson) {
    const auto result = parse("TSA_NATIVE\t1\t1\t1\n0\t0\t0\t?\t?\t?\t-50\n");
    ASSERT_TRUE(result);
    std::ostringstream output;
    write_json(output, *result);
    EXPECT_NE(output.str().find("\"sum\":\"0\""), std::string::npos);
    EXPECT_NE(output.str().find("\"sum\":null"), std::string::npos);
    EXPECT_NE(output.str().find("\"sum\":\"-50\""), std::string::npos);
    EXPECT_NE(output.str().find("\"win_rate\":null"), std::string::npos);
    EXPECT_EQ(output.str().find("NaN"), std::string::npos);
}

TEST(Protocol, BoundsLineLengthBeforeAllocatingAnUnboundedLine) {
    const auto result = parse(std::string(max_line_bytes + 1, 'x'));
    ASSERT_FALSE(result);
    EXPECT_EQ(result.error().code, ErrorCode::limits_exceeded);
}

TEST(Protocol, RejectsExtraOrMissingColumnsAndBadGroupIds) {
    for (const auto* row : {"0\t1\t?\t?\t?\t?", "0\t1\t?\t?\t?\t?\t?\textra",
                           "1\t1\t?\t?\t?\t?\t?", "0\t4\t?\t?\t?\t?\t?",
                           "0\t1\t\t?\t?\t?\t?"}) {
        EXPECT_FALSE(parse(std::string("TSA_NATIVE\t1\t1\t1\n") + row + '\n'));
    }
}

TEST(Protocol, RepeatedSerializationIsDeterministic) {
    const auto result = parse("TSA_NATIVE\t1\t2\t1\n0\t1\t100\t?\t?\t?\t?\n0\t2\t200\t?\t?\t?\t?\n");
    ASSERT_TRUE(result);
    std::ostringstream first, second;
    write_json(first, *result);
    write_json(second, *result);
    EXPECT_EQ(first.str(), second.str());
}

TEST(Protocol, NonEofReadFailureIsNotAnEmptySuccessfulBatch) {
    std::istringstream input("TSA_NATIVE\t1\t0\t0\n");
    input.setstate(std::ios::failbit);
    const auto result = read_report(input);
    ASSERT_FALSE(result);
    EXPECT_EQ(result.error().code, ErrorCode::io_error);
}

}  // namespace
