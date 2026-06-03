package com.lerobot.saas.user.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.lerobot.saas.common.api.ResultCode;
import com.lerobot.saas.common.context.UserContext;
import com.lerobot.saas.common.context.UserContextHolder;
import com.lerobot.saas.common.exception.BusinessException;
import com.lerobot.saas.common.util.PasswordUtils;
import com.lerobot.saas.organization.dao.OrganizationDao;
import com.lerobot.saas.organization.entity.SysOrganization;
import com.lerobot.saas.user.dao.UserDao;
import com.lerobot.saas.user.dto.UserCreateRequest;
import com.lerobot.saas.user.dto.UserPasswordUpdateRequest;
import com.lerobot.saas.user.dto.UserProfileUpdateRequest;
import com.lerobot.saas.user.dto.UserResetPasswordRequest;
import com.lerobot.saas.user.dto.UserUpdateRequest;
import com.lerobot.saas.user.entity.SysUser;
import com.lerobot.saas.user.service.UserService;
import com.lerobot.saas.user.vo.UserAdminVO;
import com.lerobot.saas.user.vo.UserProfileVO;
import java.util.List;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

@Service
public class UserServiceImpl implements UserService {

    private final UserDao userDao;
    private final OrganizationDao organizationDao;
    private final PasswordUtils passwordUtils;

    public UserServiceImpl(UserDao userDao, OrganizationDao organizationDao, PasswordUtils passwordUtils) {
        this.userDao = userDao;
        this.organizationDao = organizationDao;
        this.passwordUtils = passwordUtils;
    }

    @Override
    public UserProfileVO getCurrentUserProfile() {
        UserContext userContext = currentUserContext();
        UserProfileVO profile = userDao.selectUserProfileById(userContext.getUserId());
        if (profile == null) {
            throw new BusinessException(ResultCode.UNAUTHORIZED);
        }
        return profile;
    }

    @Override
    public void updateCurrentUserProfile(UserProfileUpdateRequest request) {
        UserContext userContext = currentUserContext();
        SysUser user = requireUser(userContext.getUserId());
        assertEmailAvailable(request.getEmail(), user.getId());
        user.setName(request.getName());
        user.setGender(request.getGender());
        user.setEmail(request.getEmail());
        user.setAvatarIconId(request.getAvatarIconId());
        userDao.updateById(user);
    }

    @Override
    public void updateCurrentUserPassword(UserPasswordUpdateRequest request) {
        UserContext userContext = currentUserContext();
        SysUser user = requireUser(userContext.getUserId());
        if (!passwordUtils.matches(request.getOldPassword(), user.getPasswordHash())) {
            throw new BusinessException("旧密码错误");
        }
        user.setRawPassword(request.getNewPassword());
        user.setPasswordHash(passwordUtils.encode(request.getNewPassword()));
        userDao.updateById(user);
    }

    @Override
    public List<UserAdminVO> listUsers(String keyword, String organizationId) {
        requireAdmin();
        return userDao.selectUsers(keyword, organizationId);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void createUser(UserCreateRequest request) {
        requireAdmin();
        validateOrganization(request.getOrganizationId());
        assertEmailAvailable(request.getEmail(), null);
        String rawPassword = StringUtils.hasText(request.getRawPassword()) ? request.getRawPassword() : "123456";
        SysUser user = new SysUser();
        user.setName(request.getName());
        user.setGender(request.getGender());
        user.setOrganizationId(request.getOrganizationId());
        user.setEmail(request.getEmail());
        user.setRawPassword(rawPassword);
        user.setPasswordHash(passwordUtils.encode(rawPassword));
        user.setAvatarIconId(request.getAvatarIconId());
        user.setSystemAdmin(Boolean.TRUE.equals(request.getSystemAdmin()));
        userDao.insert(user);
    }

    @Override
    public void updateUser(String userId, UserUpdateRequest request) {
        requireAdmin();
        SysUser user = requireUser(userId);
        validateOrganization(request.getOrganizationId());
        assertEmailAvailable(request.getEmail(), userId);
        user.setName(request.getName());
        user.setGender(request.getGender());
        user.setOrganizationId(request.getOrganizationId());
        user.setEmail(request.getEmail());
        user.setAvatarIconId(request.getAvatarIconId());
        user.setSystemAdmin(Boolean.TRUE.equals(request.getSystemAdmin()));
        userDao.updateById(user);
    }

    @Override
    public void deleteUser(String userId) {
        requireAdmin();
        UserContext current = currentUserContext();
        if (current.getUserId().equals(userId)) {
            throw new BusinessException("不能删除当前登录用户");
        }
        requireUser(userId);
        userDao.deleteById(userId);
    }

    @Override
    public void resetUserPassword(String userId, UserResetPasswordRequest request) {
        requireAdmin();
        SysUser user = requireUser(userId);
        user.setRawPassword(request.getNewPassword());
        user.setPasswordHash(passwordUtils.encode(request.getNewPassword()));
        userDao.updateById(user);
    }

    private UserContext currentUserContext() {
        UserContext userContext = UserContextHolder.get();
        if (userContext == null) {
            throw new BusinessException(ResultCode.UNAUTHORIZED);
        }
        return userContext;
    }

    private void requireAdmin() {
        UserContext userContext = currentUserContext();
        if (!Boolean.TRUE.equals(userContext.getSystemAdmin())) {
            throw new BusinessException(ResultCode.FORBIDDEN);
        }
    }

    private SysUser requireUser(String userId) {
        SysUser user = userDao.selectById(userId);
        if (user == null) {
            throw new BusinessException("用户不存在");
        }
        return user;
    }

    private void validateOrganization(String organizationId) {
        SysOrganization organization = organizationDao.selectById(organizationId);
        if (organization == null) {
            throw new BusinessException("所属组织不存在");
        }
    }

    private void assertEmailAvailable(String email, String excludeUserId) {
        Long count = userDao.selectCount(new LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getEmail, email)
                .ne(StringUtils.hasText(excludeUserId), SysUser::getId, excludeUserId));
        if (count != null && count > 0) {
            throw new BusinessException("邮箱已存在");
        }
    }
}
