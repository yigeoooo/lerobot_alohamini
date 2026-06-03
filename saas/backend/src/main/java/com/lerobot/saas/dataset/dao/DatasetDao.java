package com.lerobot.saas.dataset.dao;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.lerobot.saas.dataset.entity.SysDataset;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Param;

public interface DatasetDao extends BaseMapper<SysDataset> {

    @Delete("DELETE FROM sys_dataset WHERE id = #{datasetId}")
    int deleteByIdPhysical(@Param("datasetId") String datasetId);
}
