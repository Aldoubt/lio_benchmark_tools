from run_health_monitor import classify

def test_failure_never_becomes_success():
    assert classify(1,100,"")=="RUNTIME_CRASH"
    assert classify(0,0,"")=="NO_ODOMETRY"
    assert classify(0,10,"")=="SUCCESS"
