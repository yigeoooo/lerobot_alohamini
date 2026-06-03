package com.lerobot.saas.icon.dao;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.lerobot.saas.icon.entity.SysIcon;
import java.util.List;

public interface IconDao extends BaseMapper<SysIcon> {

    List<SysIcon> selectAllIcons();
}
