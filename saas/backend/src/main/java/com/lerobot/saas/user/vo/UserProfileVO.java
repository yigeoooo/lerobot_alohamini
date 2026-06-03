package com.lerobot.saas.user.vo;

import java.time.LocalDateTime;
import lombok.Data;

@Data
public class UserProfileVO {
    private String id;
    private String name;
    private Integer gender;
    private String email;
    private String organizationId;
    private String organizationName;
    private String avatarIconId;
    private String avatarIconName;
    private Boolean systemAdmin;
    private LocalDateTime createdTime;
}
