#include "tanksession/analytics.hpp"
#include <gtest/gtest.h>
#include <cmath>
#include <limits>

namespace {
using namespace tanksession;

Battle battle(std::uint32_t group, Outcome outcome, std::optional<std::int64_t> damage,
              std::optional<std::int64_t> credits = std::nullopt) {
    Battle row;
    row.group = group;
    row.outcome = outcome;
    row.metrics[0] = damage;
    row.metrics[4] = credits;
    return row;
}

TEST(Analytics, EmptyReportDoesNotInventValues) {
    const auto result = analyze({}, 0);
    ASSERT_TRUE(result);
    EXPECT_EQ(result->overall.battles, 0);
    EXPECT_TRUE(result->groups.empty());
    EXPECT_FALSE(result->overall.win_rate);
    for (const auto& metric : result->overall.metrics) {
        EXPECT_EQ(metric.known, 0);
        EXPECT_FALSE(metric.sum);
        EXPECT_FALSE(metric.mean);
        EXPECT_FALSE(metric.coverage_pct);
        EXPECT_FALSE(metric.sample_variance);
    }
}

TEST(Analytics, UnknownValuesDoNotBecomeZerosOrLosses) {
    const std::vector rows{
        battle(0, Outcome::win, 0), battle(0, Outcome::unknown, std::nullopt),
        battle(0, Outcome::draw, 100)};
    const auto result = analyze(rows, 1);
    ASSERT_TRUE(result);
    EXPECT_EQ(result->overall.outcomes_known, 2);
    EXPECT_EQ(result->overall.losses, 0);
    EXPECT_DOUBLE_EQ(*result->overall.win_rate, 50.0);
    EXPECT_EQ(result->overall.metrics[0].known, 2);
    EXPECT_EQ(result->overall.metrics[0].missing, 1);
    EXPECT_EQ(*result->overall.metrics[0].sum, 100);
    EXPECT_DOUBLE_EQ(*result->overall.metrics[0].mean, 50.0);
    EXPECT_NEAR(*result->overall.metrics[0].coverage_pct, 200.0 / 3.0, 1e-12);
}

TEST(Analytics, SampleVarianceAndLinearPercentilesHaveSpecifiedSemantics) {
    const std::vector rows{
        battle(0, Outcome::win, 0), battle(0, Outcome::loss, 10),
        battle(0, Outcome::draw, 20), battle(0, Outcome::win, 30)};
    const auto result = analyze(rows, 1);
    ASSERT_TRUE(result);
    const auto& metric = result->overall.metrics[0];
    EXPECT_DOUBLE_EQ(*metric.mean, 15.0);
    EXPECT_NEAR(*metric.sample_variance, 500.0 / 3.0, 1e-12);
    EXPECT_NEAR(*metric.stddev, std::sqrt(500.0 / 3.0), 1e-12);
    EXPECT_DOUBLE_EQ(*metric.p50, 15.0);
    EXPECT_DOUBLE_EQ(*metric.p90, 27.0);
    EXPECT_DOUBLE_EQ(*metric.minimum, 0);
    EXPECT_DOUBLE_EQ(*metric.maximum, 30);
    EXPECT_NEAR(*metric.coefficient_of_variation, std::sqrt(500.0 / 3.0) / 15.0, 1e-12);
}

TEST(Analytics, SingleObservationHasNoVarianceOrConsistencyClaim) {
    const std::vector rows{battle(0, Outcome::unknown, 12)};
    const auto result = analyze(rows, 1);
    ASSERT_TRUE(result);
    const auto& metric = result->groups[0].metrics[0];
    EXPECT_DOUBLE_EQ(*metric.p50, 12.0);
    EXPECT_DOUBLE_EQ(*metric.p90, 12.0);
    EXPECT_FALSE(metric.sample_variance);
    EXPECT_FALSE(metric.stddev);
    EXPECT_FALSE(metric.coefficient_of_variation);
}

TEST(Analytics, KnownZeroHasAnExactZeroSumAndUndefinedCv) {
    const std::vector rows{battle(0, Outcome::win, 0), battle(0, Outcome::loss, 0)};
    const auto result = analyze(rows, 1);
    ASSERT_TRUE(result);
    const auto& metric = result->overall.metrics[0];
    EXPECT_EQ(*metric.sum, 0);
    EXPECT_DOUBLE_EQ(*metric.sample_variance, 0.0);
    EXPECT_FALSE(metric.coefficient_of_variation);
}

TEST(Analytics, SignedNetIncomeIsPreservedWithoutCv) {
    const std::vector rows{battle(0, Outcome::win, 1, -10),
                           battle(0, Outcome::loss, 1, 0),
                           battle(0, Outcome::draw, 1, 4)};
    const auto result = analyze(rows, 1);
    ASSERT_TRUE(result);
    const auto& metric = result->overall.metrics[4];
    EXPECT_EQ(*metric.sum, -6);
    EXPECT_DOUBLE_EQ(*metric.mean, -2.0);
    EXPECT_DOUBLE_EQ(*metric.minimum, -10);
    EXPECT_FALSE(metric.coefficient_of_variation);
}

TEST(Analytics, DenseGroupsRemainDistinctAndReconcileWithOverall) {
    const std::vector rows{battle(1, Outcome::win, 100), battle(0, Outcome::loss, 10),
                           battle(1, Outcome::unknown, std::nullopt)};
    const auto result = analyze(rows, 2);
    ASSERT_TRUE(result);
    ASSERT_EQ(result->groups.size(), 2);
    EXPECT_EQ(result->groups[0].battles, 1);
    EXPECT_EQ(result->groups[1].battles, 2);
    EXPECT_EQ(*result->groups[0].metrics[0].sum + *result->groups[1].metrics[0].sum,
              *result->overall.metrics[0].sum);
}

TEST(Analytics, LargeNearbyValuesKeepTheirSmallVariance) {
    const std::vector rows{battle(0, Outcome::win, max_metric - 2),
                           battle(0, Outcome::loss, max_metric - 1),
                           battle(0, Outcome::draw, max_metric)};
    const auto result = analyze(rows, 1);
    ASSERT_TRUE(result);
    EXPECT_EQ(*result->overall.metrics[0].sum, max_metric * 3 - 3);
    EXPECT_DOUBLE_EQ(*result->overall.metrics[0].sample_variance, 1.0);
}

TEST(Analytics, RejectsUnsafeValuesBeforeSumming) {
    for (const auto value : std::array<std::int64_t, 3>{-1, max_metric + 1,
                                                      std::numeric_limits<std::int64_t>::max()}) {
        const std::vector rows{battle(0, Outcome::win, value)};
        const auto result = analyze(rows, 1);
        ASSERT_FALSE(result);
        EXPECT_EQ(result.error().code, ErrorCode::metric_out_of_range);
    }
    const std::vector rows{battle(0, Outcome::win, 0, -max_metric - 1)};
    EXPECT_FALSE(analyze(rows, 1));
}

TEST(Analytics, RejectsInvalidGroupsAndOutcomes) {
    EXPECT_FALSE(analyze(std::vector{battle(1, Outcome::win, 1)}, 1));
    EXPECT_FALSE(analyze(std::vector{battle(0, static_cast<Outcome>(255), 1)}, 1));
    EXPECT_FALSE(analyze(std::vector{battle(0, Outcome::win, 1)}, max_groups + 1));
    const auto unused = analyze(std::vector{battle(0, Outcome::win, 1), battle(0, Outcome::win, 1)}, 2);
    ASSERT_FALSE(unused);
    EXPECT_EQ(unused.error().code, ErrorCode::missing_group);
}

}  // namespace
