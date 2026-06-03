package com.lerobot.saas.user.dao;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.lerobot.saas.user.entity.SysUser;
import com.lerobot.saas.user.vo.UserAdminVO;
import com.lerobot.saas.user.vo.UserProfileVO;
import java.util.List;
import org.apache.ibatis.annotations.Param;

public interface UserDao extends BaseMapper<SysUser> {

    UserProfileVO selectUserProfileById(@Param("userId") String userId);

    List<UserAdminVO> selectUsers(@Param("keyword") String keyword,
                                  @Param("organizationId") String organizationId);
}
