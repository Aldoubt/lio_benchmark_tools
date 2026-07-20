#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <functional>
#include <iomanip>
#include <limits>
#include <memory>
#include <numeric>
#include <string>
#include <vector>

#include <livox_ros_driver2/msg/custom_msg.hpp>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/point_cloud2.hpp>
#include <sensor_msgs/msg/point_field.hpp>

namespace {
constexpr uint32_t kPointStep = 22;

template <typename T>
void write_value(std::vector<uint8_t>& data, size_t offset, T value) {
  std::memcpy(data.data() + offset, &value, sizeof(T));
}

sensor_msgs::msg::PointField field(
    const std::string& name, uint32_t offset, uint8_t datatype) {
  sensor_msgs::msg::PointField result;
  result.name = name;
  result.offset = offset;
  result.datatype = datatype;
  result.count = 1;
  return result;
}
}  // namespace

class CustomMsgAdapter final : public rclcpp::Node {
 public:
  CustomMsgAdapter() : Node("lio_benchmark_custommsg_to_pointcloud2") {
    input_topic_ = declare_parameter<std::string>("input_topic", "/agt/sensors/lidar/custom");
    output_topic_ = declare_parameter<std::string>("output_topic", "/lio_benchmark/points");
    metrics_path_ = declare_parameter<std::string>("metrics_path", "");
    sort_by_time_ = declare_parameter<bool>("sort_by_time", true);
    auto input_qos = rclcpp::QoS(rclcpp::KeepLast(100)).best_effort().durability_volatile();
    publisher_ = create_publisher<sensor_msgs::msg::PointCloud2>(output_topic_, rclcpp::SensorDataQoS());
    subscription_ = create_subscription<livox_ros_driver2::msg::CustomMsg>(
        input_topic_, input_qos,
        std::bind(&CustomMsgAdapter::callback, this, std::placeholders::_1));
  }

  ~CustomMsgAdapter() override { save_metrics(); }

 private:
  void callback(const livox_ros_driver2::msg::CustomMsg::SharedPtr source) {
    ++frames_;
    input_points_ += source->points.size();
    for (size_t i = 1; i < source->points.size(); ++i) {
      input_time_backtracks_ += source->points[i].offset_time < source->points[i - 1].offset_time;
    }

    std::vector<size_t> selected;
    selected.reserve(source->points.size());
    for (size_t i = 0; i < source->points.size(); ++i) {
      const auto& point = source->points[i];
      const auto tag = static_cast<uint8_t>(point.tag & 0x30U);
      if (tag != 0x00U && tag != 0x10U) {
        ++invalid_tag_points_;
        continue;
      }
      if (!std::isfinite(point.x) || !std::isfinite(point.y) || !std::isfinite(point.z)) {
        ++non_finite_points_;
        continue;
      }
      selected.push_back(i);
    }
    if (sort_by_time_) {
      std::stable_sort(selected.begin(), selected.end(), [&](size_t lhs, size_t rhs) {
        return source->points[lhs].offset_time < source->points[rhs].offset_time;
      });
    }

    sensor_msgs::msg::PointCloud2 output;
    output.header = source->header;
    output.height = 1;
    output.width = static_cast<uint32_t>(selected.size());
    output.fields = {
        field("x", 0, sensor_msgs::msg::PointField::FLOAT32),
        field("y", 4, sensor_msgs::msg::PointField::FLOAT32),
        field("z", 8, sensor_msgs::msg::PointField::FLOAT32),
        field("intensity", 12, sensor_msgs::msg::PointField::FLOAT32),
        field("ring", 16, sensor_msgs::msg::PointField::UINT16),
        field("time", 18, sensor_msgs::msg::PointField::FLOAT32),
    };
    output.is_bigendian = false;
    output.point_step = kPointStep;
    output.row_step = output.point_step * output.width;
    output.is_dense = true;
    output.data.resize(output.row_step);

    uint32_t previous_offset = 0;
    bool first = true;
    for (size_t output_index = 0; output_index < selected.size(); ++output_index) {
      const auto& point = source->points[selected[output_index]];
      const size_t base = output_index * kPointStep;
      const float intensity = static_cast<float>(point.reflectivity);
      const uint16_t ring = point.line;
      const float time = static_cast<float>(point.offset_time) * 1.0e-9F;
      write_value(output.data, base + 0, point.x);
      write_value(output.data, base + 4, point.y);
      write_value(output.data, base + 8, point.z);
      write_value(output.data, base + 12, intensity);
      write_value(output.data, base + 16, ring);
      write_value(output.data, base + 18, time);
      output_time_backtracks_ += !first && point.offset_time < previous_offset;
      previous_offset = point.offset_time;
      first = false;
      ring_counts_.at(std::min<size_t>(ring, ring_counts_.size() - 1))++;
      time_min_s_ = std::min(time_min_s_, static_cast<double>(time));
      time_max_s_ = std::max(time_max_s_, static_cast<double>(time));
    }
    output_points_ += selected.size();
    publisher_->publish(std::move(output));
  }

  void save_metrics() const {
    if (metrics_path_.empty()) return;
    std::ofstream stream(metrics_path_);
    if (!stream) return;
    const auto dropped = input_points_ - output_points_;
    const double ratio = input_points_ ? static_cast<double>(dropped) / input_points_ : 0.0;
    stream << std::setprecision(15)
           << "{\n  \"implementation\": \"cpp\",\n"
           << "  \"frames\": " << frames_ << ",\n"
           << "  \"input_points\": " << input_points_ << ",\n"
           << "  \"output_points\": " << output_points_ << ",\n"
           << "  \"missing_fields\": 0,\n"
           << "  \"invalid_tag_points\": " << invalid_tag_points_ << ",\n"
           << "  \"non_finite_points\": " << non_finite_points_ << ",\n"
           << "  \"invalid_time_points\": 0,\n"
           << "  \"input_time_backtracks\": " << input_time_backtracks_ << ",\n"
           << "  \"output_time_backtracks\": " << output_time_backtracks_ << ",\n"
           << "  \"time_min_s\": " << (output_points_ ? time_min_s_ : 0.0) << ",\n"
           << "  \"time_max_s\": " << (output_points_ ? time_max_s_ : 0.0) << ",\n"
           << "  \"ring_min\": 0,\n  \"ring_max\": 3,\n"
           << "  \"ring_counts\": {\"0\": " << ring_counts_[0]
           << ", \"1\": " << ring_counts_[1] << ", \"2\": " << ring_counts_[2]
           << ", \"3\": " << ring_counts_[3] << "},\n"
           << "  \"dropped_points\": " << dropped << ",\n"
           << "  \"dropped_ratio\": " << ratio << ",\n"
           << "  \"time_semantics\": \"FLOAT32 seconds relative to CustomMsg header/timebase\",\n"
           << "  \"ring_semantics\": \"exact uint8 CustomPoint.line value widened to uint16; no synthetic rings\"\n}\n";
  }

  std::string input_topic_, output_topic_, metrics_path_;
  bool sort_by_time_ = true;
  rclcpp::Publisher<sensor_msgs::msg::PointCloud2>::SharedPtr publisher_;
  rclcpp::Subscription<livox_ros_driver2::msg::CustomMsg>::SharedPtr subscription_;
  uint64_t frames_ = 0, input_points_ = 0, output_points_ = 0;
  uint64_t invalid_tag_points_ = 0, non_finite_points_ = 0;
  uint64_t input_time_backtracks_ = 0, output_time_backtracks_ = 0;
  std::array<uint64_t, 4> ring_counts_{};
  double time_min_s_ = std::numeric_limits<double>::infinity();
  double time_max_s_ = -std::numeric_limits<double>::infinity();
};

int main(int argc, char** argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<CustomMsgAdapter>());
  rclcpp::shutdown();
  return 0;
}
