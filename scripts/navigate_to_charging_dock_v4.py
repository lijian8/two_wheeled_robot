#! /usr/bin/env python3

"""
Description:
  Navigate to a charging dock once the battery gets low.
  We first navigate to a staging area in front of the docking station (~1.5 meters is good)
  We rotate around to search for the ArUco marker using the robot's front camera.
  Once the ArUco marker is detected, move towards it, making minor heading adjustments as necessary.
  Stop once the robot gets close enough to the charging dock or starts charging.
-------
Subscription Topics:
  Current battery state
  /battery_status - sensor_msgs/BatteryState
  
  A boolean variable that is True of ArUco marker detected, otherwise False
  /aruco_marker_detected – std_msgs/Bool
  
  The number of pixels offset of the ArUco marker from the center of the camera image
  /aruco_marker_offset - std_msgs/Int32
  
  LaserScan readings for object detection
  /scan - sensor_msgs/LaserScan
-------
Publishing Topics:
  Velocity command to navigate to the charging dock.
  /cmd_vel - geometry_msgs/Twist
-------
Author: Addison Sears-Collins
Website: AutomaticAddison.com
Date: January 14, 2022
"""

import math # Math library
import time  # Time library

from rclpy.duration import Duration # Handles time for ROS 2
import rclpy # Python client library for ROS 2
from rclpy.node import Node # Handles the creation of nodes
from rclpy.executors import MultiThreadedExecutor
from rclpy.qos import qos_profile_sensor_data # Handle quality of service for LaserScan data
from nav2_simple_commander.robot_navigator import BasicNavigator, NavigationResult # Helper module
from geometry_msgs.msg import PoseStamped # Pose with ref frame and timestamp
from geometry_msgs.msg import Twist # Velocity command
from sensor_msgs.msg import BatteryState # Battery status
from sensor_msgs.msg import LaserScan # Handle LIDAR scans
from std_msgs.msg import Float64MultiArray # Handle float64 arrays  ###############################Remove this later
from std_msgs.msg import Bool # Handle boolean values
from std_msgs.msg import Int32 # Handle integer values

# Holds the current pose of the aruco_marker
# base_link (parent frame) -> aruco_marker (child frame)
current_x = 0.0
current_y = 0.0
current_yaw_angle = 0.0

# Holds the current state of the battery
this_battery_state = BatteryState()
prev_battery_state = BatteryState()

# Flag for detecting the change in the battery state
low_battery = False
low_battery_min_threshold = 0.25

# Flag to determine if the ArUco marker has been detected (True or False)
aruco_marker_detected = False

# Store the ArUco marker center offset (in pixels)
aruco_center_offset = 0

# Keep track of obstacles in front of the robot in meters
obstacle_distance_front = 999999.9

class ConnectToChargingDockNavigator(Node):
    """
    Navigates and connects to the charging dock
    """      
    def __init__(self):
  
      # Initialize the class using the constructor
      super().__init__('connect_to_charging_dock_navigator')
    
      # Create a publisher
      # This node publishes the desired linear and angular velocity of the robot
      self.publisher_cmd_vel = self.create_publisher(
        Twist,
        '/cmd_vel',
        10)  
      timer_period = 0.1
      self.timer = self.create_timer(timer_period, self.navigate_to_dock_staging_area)

      # Declare linear and angular velocities
      self.linear_velocity = 0.08  # meters per second
      self.angular_velocity = 0.1 # radians per second
      
      # Keep track of which goal we're headed towards
      self.goal_idx = 0

      # Holds the goal pose of the robot
      # Parent frame: base_link
      # Child frame: aruco_marker
      self.goal_x = 0.36
      self.goal_y = 0.0
      self.goal_yaw_angle = -1.5708

      # Declare distance metrics in meters
      self.distance_goal_tolerance = 0.05
      self.reached_distance_goal = False      

      # Declare angle metrics in radians
      self.yaw_goal_tolerance = 0.05
      self.reached_yaw_angle_goal = False 
        
    def navigate_to_dock_staging_area(self):
      """
      Navigate from somewhere in the environment to a staging area near
      the charging dock.
      """    
      global low_battery
      
      # If we have enough battery, don't navigate to the charging dock.
      if low_battery == False:
        return None 
      
      self.get_logger().info('Low battery. Navigating to the charging dock...')
      
      # Launch the ROS 2 Navigation Stack
      navigator = BasicNavigator()

      # Wait for navigation to fully activate. Use this line if autostart is set to true.
      navigator.waitUntilNav2Active()

      # If desired, you can change or load the map as well
      # navigator.changeMap('/path/to/map.yaml')

      # You may use the navigator to clear or obtain costmaps
      # navigator.clearAllCostmaps()  # also have clearLocalCostmap() and clearGlobalCostmap()
      # global_costmap = navigator.getGlobalCostmap()
      # local_costmap = navigator.getLocalCostmap()

      # Set the robot's staging area pose 
      # map (parent frame)
      # base_link (child frame)
      staging_area_pose = PoseStamped()
      staging_area_pose.header.frame_id = 'map'
      staging_area_pose.header.stamp = navigator.get_clock().now().to_msg()
      staging_area_pose.pose.position.x = 0.0
      staging_area_pose.pose.position.y = 2.0
      staging_area_pose.pose.position.z = 0.25
      staging_area_pose.pose.orientation.x = 0.0
      staging_area_pose.pose.orientation.y = 0.0
      staging_area_pose.pose.orientation.z = 0.0
      staging_area_pose.pose.orientation.w = 1.0

      # Go to the staging area pose
      navigator.goToPose(staging_area_pose)

      i = 0

      # Keep doing stuff as long as the robot is moving towards the staging area
      while not navigator.isNavComplete():
      
        # Do something with the feedback
        i = i + 1        
        feedback = navigator.getFeedback()
        
        if feedback and i % 5 == 0:
          print('Distance remaining: ' + '{:.2f}'.format(
            feedback.distance_remaining) + ' meters.')
   
          # Some navigation timeout to demo cancellation
          #if Duration.from_msg(feedback.navigation_time) > Duration(seconds=1800.0):
            #navigator.cancelNav()

      # Do something depending on the return code
      result = navigator.getResult()
      
      if result == NavigationResult.SUCCEEDED:
        self.get_logger().info('Successfully reached charging dock staging area...')
        low_battery = False
        self.connect_to_dock()
      elif result == NavigationResult.CANCELED:
        self.get_logger().info('Goal was canceled!')
      elif result == NavigationResult.FAILED:
        self.get_logger().info('Goal failed!')
      else:
        self.get_logger().info('Goal has an invalid return status!')  
        
    def connect_to_dock(self): 
      """
      Navigate and connect to the charging dock.
      """ 
      
      # While the battery is not charging
      while this_battery_state.power_supply_status != 1:
    
        # Publish the current battery state
        self.get_logger().info('NOT CHARGING...')
        
        if (self.goal_idx == 0):
          self.go_to_line()
          self.get_logger().info('Going to perpendicular line to ArUco marker...')
          self.get_logger().info("Obstacle detected at '{}' meters".format(aruco_marker_detected)) 
        elif (self.goal_idx == 1):
          self.align_with_aruco_marker()
          self.get_logger().info('Aligning with the ArUco marker...')
          self.get_logger().info("Obstacle detected at '{}' meters".format(aruco_marker_detected))
        elif (self.goal_idx == 2):
          self.go_to_aruco_marker()
          self.get_logger().info('Going to the ArUco marker...')
          self.get_logger().info("Obstacle detected at '{}' meters".format(aruco_marker_detected))
        else:
          # Stop the robot
          cmd_vel_msg = Twist()
          cmd_vel_msg.linear.x = 0.0
          cmd_vel_msg.angular.z = 0.0
          self.publisher_cmd_vel.publish(cmd_vel_msg)
          self.get_logger().info('Robot is idle...')
          self.get_logger().info("Obstacle detected at '{}' meters".format(aruco_marker_detected)) 
    
        time.sleep(0.02)
    
      self.get_logger().info('CHARGING...')
      self.get_logger().info('Successfully connected to the charging dock!')
    
    def get_distance_to_goal(self):
      """
      Get the distance between the current x,y coordinate and the desired x,y coordinate
      The unit is meters.
      """
      distance_to_goal = math.sqrt(math.pow(self.goal_x - current_x, 2) + math.pow(
        self.goal_y - current_y, 2))
      return distance_to_goal
        
    def get_radians_to_goal(self):
      """
      Get the yaw goal angle error in radians
      """
      yaw_goal_angle_error = self.goal_yaw_angle - current_yaw_angle

      # Make sure the yaw angle error falls within -PI to PI range
      if (yaw_goal_angle_error > math.pi):
        yaw_goal_angle_error = yaw_goal_angle_error - (2 * math.pi)
      if (yaw_goal_angle_error < -math.pi):
        yaw_goal_angle_error = yaw_goal_angle_error + (2 * math.pi)
      
      return yaw_goal_angle_error
      
    def go_to_line(self):
      """
      Go to the line that is perpendicular to the ArUco marker
      """
      distance_to_goal = math.fabs(current_x)
      yaw_goal_error = current_yaw_angle
      
      # Create a velocity message
      cmd_vel_msg = Twist()

      # Orient towards the yaw goal angle
      if (math.fabs(yaw_goal_error) > self.yaw_goal_tolerance and self.reached_yaw_angle_goal == False):
        cmd_vel_msg.angular.z = self.angular_velocity      
      
      # If we are not yet at the target x position, go there now.
      elif (distance_to_goal > self.distance_goal_tolerance):
        self.reached_yaw_angle_goal = True
        
        if current_x > 0:
          cmd_vel_msg.linear.x = self.linear_velocity
        else: 
          cmd_vel_msg.linear.x = -self.linear_velocity
      
      # Reached perpendicular line 
      else:
        # Go to the next goal
        self.goal_idx = self.goal_idx + 1    
        self.get_logger().info('Going to the ArUco marker...')
        self.reached_yaw_angle_goal = False

      # Publish the velocity message  
      self.publisher_cmd_vel.publish(cmd_vel_msg) 

    def align_with_aruco_marker(self):
      """
      Align with the ArUco marker
      """
      yaw_goal_error = self.get_radians_to_goal()
      
      # Create a velocity message
      cmd_vel_msg = Twist()

      # Orient towards the yaw goal angle
      if (math.fabs(yaw_goal_error) > self.yaw_goal_tolerance and self.reached_yaw_angle_goal == False):
        cmd_vel_msg.angular.z = self.angular_velocity      
      
      else:
        # Go to the next goal
        self.goal_idx = self.goal_idx + 1    
        self.get_logger().info('Going to the ArUco marker...')

      # Publish the velocity message  
      self.publisher_cmd_vel.publish(cmd_vel_msg) 
            
    def go_to_aruco_marker(self):
      """
      Go straight to the ArUco marker
      """
      distance_to_goal = self.get_distance_to_goal()
      yaw_goal_error = self.get_radians_to_goal()
            
      cmd_vel_msg = Twist()
      
      # Follow the perpendicular line to the ArUco marker
      if (current_y > self.distance_goal_tolerance and self.reached_distance_goal == False):
        cmd_vel_msg.angular.z = self.angular_velocity 
      elif (current_y < -self.distance_goal_tolerance and self.reached_distance_goal == False):
        cmd_vel_msg.angular.z = -self.angular_velocity 
      elif (math.fabs(distance_to_goal) > self.distance_goal_tolerance and self.reached_distance_goal == False):
        cmd_vel_msg.linear.x = self.linear_velocity        
      # Goal position and orientation achieved
      else:
        self.goal_idx = self.goal_idx + 1 
        self.get_logger().info('Arrived at the charging dock...')   
        self.reached_distance_goal = True

      # Publish the velocity message  
      self.publisher_cmd_vel.publish(cmd_vel_msg)   

class BatteryStateSubscriber(Node):
    """
    Subscriber node to the current battery state
    """      
    def __init__(self):
  
      # Initialize the class using the constructor
      super().__init__('battery_state_subscriber')
    
      # Create a subscriber 
      # This node subscribes to messages of type
      # sensor_msgs/BatteryState
      self.subscription_battery_state = self.create_subscription(
        BatteryState,
        '/battery_status',
        self.get_battery_state,
        10)
      
    def get_battery_state(self, msg):
      """
      Update the current battery state.
      """
      global this_battery_state
      global prev_battery_state
      global low_battery
      prev_battery_state = this_battery_state
      this_battery_state = msg
      
      # Check for low battery
      if prev_battery_state.percentage >= low_battery_min_threshold and this_battery_state.percentage < low_battery_min_threshold:
        low_battery = True
        
class ArucoMarkerSubscriber(Node):
    """
    Subscriber node to help for the ArUco marker navigation routine.
    """      
    def __init__(self):
  
      # Initialize the class using the constructor
      super().__init__('aruco_marker_subscriber')
    
      # Create a subscriber 
      # This node subscribes to messages of type
      # std_msgs/Bool
      self.subscription_aruco_detected = self.create_subscription(
        Bool,
        '/aruco_marker_detected', 
        self.get_aruco_detected,
        1)

      # Create a subscriber 
      # This node subscribes to messages of type
      # std_msgs/Int32
      self.subscription_center_offset = self.create_subscription(
        Int32,
        '/aruco_marker_offset', 
        self.get_center_offset,
        1)
        
      # Create a subscriber 
      # This node subscribes to messages of type
      # sensor_msgs/LaserScan
      self.subscription_laser_scan = self.create_subscription(
        LaserScan,
        '/scan', 
        self.scan_callback,
        qos_profile=qos_profile_sensor_data)

    def get_aruco_detected(self, msg):
      """
      Update if the ArUco marker has been detected or not
      """
      global aruco_marker_detected 
      aruco_marker_detected = msg.data
        
    def get_center_offset(self, msg):
      """
      Update the ArUco marker center offset
      """
      global aruco_center_offset
      aruco_center_offset = msg.data
            
    def scan_callback(self, msg):
      """
      Update obstacle distance.
      """
      global obstacle_distance_front
      obstacle_distance_front = msg.ranges[179]
        
def main(args=None):
  """
  Entry point for the program.
  """
  
  # Initialize the rclpy library
  rclpy.init(args=args)
  
  try: 
  
    # Create the nodes
    connect_to_charging_dock_navigator = ConnectToChargingDockNavigator()
    battery_state_subscriber = BatteryStateSubscriber()
    aruco_marker_subscriber = ArucoMarkerSubscriber()
    
    # Set up mulithreading
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(connect_to_charging_dock_navigator)
    executor.add_node(battery_state_subscriber)
    executor.add_node(aruco_marker_subscriber)
    
    try:
      # Spin the nodes to execute the callbacks
      executor.spin()
    finally:
      # Shutdown the nodes
      executor.shutdown()
      connect_to_charging_dock_navigator.destroy_node()
      battery_state_subscriber.destroy_node()
      aruco_marker_subscriber.destroy_node()

  finally:
    # Shutdown
    rclpy.shutdown()

if __name__ == '__main__':
  main()
