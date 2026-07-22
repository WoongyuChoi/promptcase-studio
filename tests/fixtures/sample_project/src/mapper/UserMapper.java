package sample.mapper;

import sample.dto.UserDto;

public interface UserMapper {
    UserDto selectActiveUser(String userId);
}

