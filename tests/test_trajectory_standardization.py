from standardize_trajectory import normalize_samples

def row(t,q=(0,0,0,1)):
    return dict(timestamp_s=t,x_m=t,y_m=0,z_m=0,qx=q[0],qy=q[1],qz=q[2],qw=q[3])

def test_sort_drop_zero_and_duplicates():
    rows,meta=normalize_samples([row(2),row(0),row(1),row(1)],"/odom")
    assert [x["timestamp_s"] for x in rows]==[1,2]
    assert meta["zero_timestamp_samples_removed"]==1
    assert meta["duplicate_timestamps_removed"]==1
    assert meta["input_time_backtracks"]==1
