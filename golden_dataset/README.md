# Golden dataset

A small, curated set of inputs every Travel Planner prompt must still
handle correctly. The Verifier gate runs both the baseline and the
proposed prompt against this dataset and rejects any fix whose golden
pass rate drops more than `golden_regression_limit` (default 2 %).

Adding cases is cheap; removing them is expensive. Every case
represents a class of user query we've decided is non-negotiable.
