package sample.service;

import sample.dto.UserDto;
import sample.mapper.UserMapper;

public class UserService {
    private final UserMapper userMapper;

    public UserService(UserMapper userMapper) {
        this.userMapper = userMapper;
    }

    public UserDto findActiveUser(String userId) {
        return userMapper.selectActiveUser(userId);
    }
}

