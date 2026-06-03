package com.lerobot.saas.user.vo;

import java.time.LocalDateTime;
import lombok.Data;

@Data
public class UserAdminVO {
    private String id;
    private String name;
    private Integer gender;
    private String organizationId;
    private String organizationName;
    private String email;
    private String avatarIconId;
    private String avatarIconName;
    private Boolean systemAdmin;
    private String rawPassword;
    private LocalDateTime createdTime;
}
