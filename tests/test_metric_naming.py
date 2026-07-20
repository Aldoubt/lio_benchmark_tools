import pytest
from evaluation import validate_metric_names

def test_ground_truth_names_are_forbidden_without_truth():
    with pytest.raises(ValueError):validate_metric_names({"ate_rmse_m":1.0},False)
    validate_metric_names({"z_end_delta_m":1.0,"metric_class":"diagnostic"},False)
