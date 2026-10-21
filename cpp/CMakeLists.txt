cmake_minimum_required(VERSION 3.16)
project(legv8 CXX)
add_executable(legv8 legv8.cpp)
target_compile_features(legv8 PRIVATE cxx_std_17)
