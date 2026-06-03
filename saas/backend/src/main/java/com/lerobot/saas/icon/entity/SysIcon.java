package com.lerobot.saas.icon.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import com.lerobot.saas.common.entity.BaseEntity;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@EqualsAndHashCode(callSuper = true)
@TableName("sys_icon")
public class SysIcon extends BaseEntity {
    private String iconName;
    private String componentName;
    private String description;
}
