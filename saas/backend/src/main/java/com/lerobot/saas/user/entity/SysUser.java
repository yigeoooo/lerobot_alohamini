package com.lerobot.saas.user.entity;

import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import com.lerobot.saas.common.entity.BaseEntity;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@EqualsAndHashCode(callSuper = true)
@TableName("sys_user")
public class SysUser extends BaseEntity {
    private String name;
    private Integer gender;
    private String organizationId;
    private String email;
    private String passwordHash;
    private String rawPassword;
    private String avatarIconId;
    private Boolean systemAdmin;

    @TableField(exist = false)
    private String organizationName;

    @TableField(exist = false)
    private String avatarIconName;
}
