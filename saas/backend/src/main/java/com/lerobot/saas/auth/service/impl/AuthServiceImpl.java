package com.lerobot.saas.auth.service.impl;

import com.lerobot.saas.auth.dao.AuthDao;
import com.lerobot.saas.auth.dto.LoginRequest;
import com.lerobot.saas.auth.service.AuthService;
import com.lerobot.saas.auth.vo.AuthRoutePermissionVO;
import com.lerobot.saas.auth.vo.LoginUserVO;
import com.lerobot.saas.auth.vo.LoginVO;
import com.lerobot.saas.common.api.ResultCode;
import com.lerobot.saas.common.context.UserContext;
import com.lerobot.saas.common.context.UserContextHolder;
import com.lerobot.saas.common.exception.BusinessException;
import com.lerobot.saas.common.util.JwtUtils;
import com.lerobot.saas.common.util.PasswordUtils;
import com.lerobot.saas.user.entity.SysUser;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

@Service
public class AuthServiceImpl implements AuthService {

    private final AuthDao authDao;
    private final JwtUtils jwtUtils;
    private final PasswordUtils passwordUtils;

    public AuthServiceImpl(AuthDao authDao, JwtUtils jwtUtils, PasswordUtils passwordUtils) {
        this.authDao = authDao;
        this.jwtUtils = jwtUtils;
        this.passwordUtils = passwordUtils;
    }

    @Override
    public LoginVO login(LoginRequest request) {
        SysUser user = authDao.selectLoginUserByEmail(request.getEmail());
        if (user == null || !StringUtils.hasText(user.getPasswordHash())
                || !passwordUtils.matches(request.getPassword(), user.getPasswordHash())) {
            throw new BusinessException(ResultCode.UNAUTHORIZED.getCode(), "邮箱或密码错误");
        }
        return buildLoginVO(user);
    }

    @Override
    public LoginVO getCurrentProfile() {
        UserContext userContext = UserContextHolder.get();
        if (userContext == null) {
            throw new BusinessException(ResultCode.UNAUTHORIZED);
        }
        SysUser user = authDao.selectLoginUserById(userContext.getUserId());
        if (user == null) {
            throw new BusinessException(ResultCode.UNAUTHORIZED);
        }
        return buildLoginVO(user);
    }

    private LoginVO buildLoginVO(SysUser user) {
        List<AuthRoutePermissionVO> routePermissions = Boolean.TRUE.equals(user.getSystemAdmin())
                ? authDao.selectAllRoutePermissions()
                : authDao.selectRoutePermissionsByOrganizationId(user.getOrganizationId());
        Map<String, Object> claims = new HashMap<>();
        claims.put("organizationId", user.getOrganizationId());
        claims.put("systemAdmin", Boolean.TRUE.equals(user.getSystemAdmin()));
        String token = jwtUtils.generateToken(user.getId(), claims);
        return new LoginVO(token, new LoginUserVO(
                user.getId(),
                user.getName(),
                user.getGender(),
                user.getEmail(),
                user.getOrganizationId(),
                user.getOrganizationName(),
                user.getAvatarIconId(),
                user.getAvatarIconName(),
                Boolean.TRUE.equals(user.getSystemAdmin())
        ), routePermissions);
    }
}
