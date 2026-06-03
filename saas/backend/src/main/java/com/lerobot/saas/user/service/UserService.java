package com.lerobot.saas.user.service;

import com.lerobot.saas.user.dto.UserCreateRequest;
import com.lerobot.saas.user.dto.UserPasswordUpdateRequest;
import com.lerobot.saas.user.dto.UserProfileUpdateRequest;
import com.lerobot.saas.user.dto.UserResetPasswordRequest;
import com.lerobot.saas.user.dto.UserUpdateRequest;
import com.lerobot.saas.user.vo.UserAdminVO;
import com.lerobot.saas.user.vo.UserProfileVO;
import java.util.List;

public interface UserService {

    UserProfileVO getCurrentUserProfile();

    void updateCurrentUserProfile(UserProfileUpdateRequest request);

    void updateCurrentUserPassword(UserPasswordUpdateRequest request);

    List<UserAdminVO> listUsers(String keyword, String organizationId);

    void createUser(UserCreateRequest request);

    void updateUser(String userId, UserUpdateRequest request);

    void deleteUser(String userId);

    void resetUserPassword(String userId, UserResetPasswordRequest request);
}
