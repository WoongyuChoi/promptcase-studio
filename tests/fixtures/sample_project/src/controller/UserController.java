package sample.controller;

import sample.service.UserService;

public class UserController {
    private final UserService userService;

    public UserController(UserService userService) {
        this.userService = userService;
    }

    public void findUser(String userId) {
        userService.findActiveUser(userId);
    }
}
