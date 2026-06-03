package com.lerobot.saas.permission.dao;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.lerobot.saas.permission.entity.SysOrganizationRoutePermission;
import java.util.List;
import org.apache.ibatis.annotations.Param;

public interface OrganizationRoutePermissionDao extends BaseMapper<SysOrganizationRoutePermission> {

    List<String> selectRouteIdsByOrganizationId(@Param("organizationId") String organizationId);

    void deleteByOrganizationIdPhysical(@Param("organizationId") String organizationId);
}
