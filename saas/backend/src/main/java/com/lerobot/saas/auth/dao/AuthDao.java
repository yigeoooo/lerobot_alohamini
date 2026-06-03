package com.lerobot.saas.auth.dao;

import com.lerobot.saas.auth.vo.AuthRoutePermissionVO;
import com.lerobot.saas.user.entity.SysUser;
import java.util.List;
import org.apache.ibatis.annotations.Param;

public interface AuthDao {

    SysUser selectLoginUserByEmail(@Param("email") String email);

    SysUser selectLoginUserById(@Param("userId") String userId);

    List<AuthRoutePermissionVO> selectRoutePermissionsByOrganizationId(@Param("organizationId") String organizationId);

    List<AuthRoutePermissionVO> selectAllRoutePermissions();
}
