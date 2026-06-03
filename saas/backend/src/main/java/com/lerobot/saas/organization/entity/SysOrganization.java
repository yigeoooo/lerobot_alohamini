package com.lerobot.saas.organization.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import com.lerobot.saas.common.entity.BaseEntity;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@EqualsAndHashCode(callSuper = true)
@TableName("sys_organization")
public class SysOrganization extends BaseEntity {
    private String organizationName;
    private String organizationCode;
    private String description;
}
