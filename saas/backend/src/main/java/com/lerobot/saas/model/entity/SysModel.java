package com.lerobot.saas.model.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import com.lerobot.saas.common.entity.BaseEntity;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@EqualsAndHashCode(callSuper = true)
@TableName("sys_model")
public class SysModel extends BaseEntity {
    private String modelCode;
    private String modelName;
}
