package com.lerobot.saas.permission.dao;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.lerobot.saas.permission.entity.SysRoutePermission;
import java.util.List;

public interface RoutePermissionDao extends BaseMapper<SysRoutePermission> {

    List<SysRoutePermission> selectAllActiveRoutePermissions();
}
