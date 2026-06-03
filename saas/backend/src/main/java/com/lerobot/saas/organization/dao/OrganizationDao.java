package com.lerobot.saas.organization.dao;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.lerobot.saas.organization.entity.SysOrganization;
import java.util.List;
import org.apache.ibatis.annotations.Param;

public interface OrganizationDao extends BaseMapper<SysOrganization> {

    List<SysOrganization> selectOrganizations(@Param("keyword") String keyword);
}
