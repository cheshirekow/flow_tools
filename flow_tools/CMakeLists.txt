set(flow_tools_py_files
    __init__.py
    __main__.py
    gerrit_util.py
    git_util.py
    integrations.py
    jira_util.py
    orm.py)

add_custom_command(OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/flow_tools_format.stamp
                   COMMAND autopep8 -i ${flow_tools_py_files}
                   COMMAND python -Bm cmake_format -i CMakeLists.txt
                           doc/CMakeLists.txt test/CMakeLists.txt
                   COMMAND touch
                           ${CMAKE_CURRENT_BINARY_DIR}/flow_tools_format.stamp
                   DEPENDS ${flow_tools_py_files}
                   WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR})
add_custom_target(flow_tools_format
                  DEPENDS ${CMAKE_CURRENT_BINARY_DIR}/flow_tools_format.stamp)
add_dependencies(format flow_tools_format)

add_custom_command(OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/flow_tools_lint.stamp
                   COMMAND pylint ${flow_tools_py_files}
                   COMMAND touch
                           ${CMAKE_CURRENT_BINARY_DIR}/flow_tools_lint.stamp
                   DEPENDS ${flow_tools_py_files}
                   WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR})
add_custom_target(flow_tools_lint
                  DEPENDS ${CMAKE_CURRENT_BINARY_DIR}/flow_tools_lint.stamp)

add_dependencies(lint flow_tools_lint)

add_subdirectory(doc)
