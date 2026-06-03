package com.lerobot.saas.user.controller;

import com.lerobot.saas.common.api.ApiResponse;
import com.lerobot.saas.user.dto.UserCreateRequest;
import com.lerobot.saas.user.dto.UserPasswordUpdateRequest;
import com.lerobot.saas.user.dto.UserProfileUpdateRequest;
import com.lerobot.saas.user.dto.UserResetPasswordRequest;
import com.lerobot.saas.user.dto.UserUpdateRequest;
import com.lerobot.saas.user.service.UserService;
import com.lerobot.saas.user.vo.UserAdminVO;
import com.lerobot.saas.user.vo.UserProfileVO;
import jakarta.validation.Valid;
import java.util.List;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/users")
public class UserController {

    private final UserService userService;

    public UserController(UserService userService) {
        this.userService = userService;
    }

    @GetMapping("/me")
    public ApiResponse<UserProfileVO> me() {
        return ApiResponse.success(userService.getCurrentUserProfile());
    }

    @PutMapping("/me/profile")
    public ApiResponse<Void> updateProfile(@Valid @RequestBody UserProfileUpdateRequest request) {
        userService.updateCurrentUserProfile(request);
        return ApiResponse.success("更新成功", null);
    }

    @PutMapping("/me/password")
    public ApiResponse<Void> updatePassword(@Valid @RequestBody UserPasswordUpdateRequest request) {
        userService.updateCurrentUserPassword(request);
        return ApiResponse.success("密码修改成功", null);
    }

    @GetMapping
    public ApiResponse<List<UserAdminVO>> list(@RequestParam(required = false) String keyword,
                                               @RequestParam(required = false) String organizationId) {
        return ApiResponse.success(userService.listUsers(keyword, organizationId));
    }

    @PostMapping
    public ApiResponse<Void> create(@Valid @RequestBody UserCreateRequest request) {
        userService.createUser(request);
        return ApiResponse.success("用户创建成功", null);
    }

    @PutMapping("/{userId}")
    public ApiResponse<Void> update(@PathVariable String userId,
                                    @Valid @RequestBody UserUpdateRequest request) {
        userService.updateUser(userId, request);
        return ApiResponse.success("用户更新成功", null);
    }

    @DeleteMapping("/{userId}")
    public ApiResponse<Void> delete(@PathVariable String userId) {
        userService.deleteUser(userId);
        return ApiResponse.success("用户删除成功", null);
    }

    @PutMapping("/{userId}/reset-password")
    public ApiResponse<Void> resetPassword(@PathVariable String userId,
                                           @Valid @RequestBody UserResetPasswordRequest request) {
        userService.resetUserPassword(userId, request);
        return ApiResponse.success("密码重置成功", null);
    }
}
