-- LeRobot AlohaMini SaaS 数据库初始化脚本
-- 用途：初始化开发库 lerobot_saas_dev 与测试库 lerobot_saas_test
-- 默认管理员：632084210@qq.com / Admin@123456

CREATE DATABASE IF NOT EXISTS lerobot_saas_dev DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
CREATE DATABASE IF NOT EXISTS lerobot_saas_test DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS lerobot_saas_dev.sys_organization (
    id VARCHAR(32) NOT NULL PRIMARY KEY,
    organization_name VARCHAR(100) NOT NULL,
    organization_code VARCHAR(100) NULL,
    description VARCHAR(255) NULL,
    sort INT NOT NULL DEFAULT 0,
    deleted TINYINT NOT NULL DEFAULT 0,
    created_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lerobot_saas_dev.sys_icon (
    id VARCHAR(32) NOT NULL PRIMARY KEY,
    icon_name VARCHAR(100) NOT NULL,
    component_name VARCHAR(100) NOT NULL,
    description VARCHAR(255) NULL,
    sort INT NOT NULL DEFAULT 0,
    deleted TINYINT NOT NULL DEFAULT 0,
    created_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lerobot_saas_dev.sys_user (
    id VARCHAR(32) NOT NULL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    gender TINYINT NOT NULL DEFAULT 1,
    organization_id VARCHAR(32) NOT NULL,
    email VARCHAR(100) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    raw_password VARCHAR(100) NOT NULL,
    avatar_icon_id VARCHAR(32) NULL,
    system_admin TINYINT NOT NULL DEFAULT 0,
    sort INT NOT NULL DEFAULT 0,
    deleted TINYINT NOT NULL DEFAULT 0,
    created_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_sys_user_email (email)
);

CREATE TABLE IF NOT EXISTS lerobot_saas_dev.sys_route_permission (
    id VARCHAR(32) NOT NULL PRIMARY KEY,
    route_name VARCHAR(100) NOT NULL,
    route_path VARCHAR(120) NOT NULL,
    component_path VARCHAR(150) NOT NULL,
    title VARCHAR(100) NOT NULL,
    icon VARCHAR(60) NULL,
    admin_only TINYINT NOT NULL DEFAULT 0,
    sort INT NOT NULL DEFAULT 0,
    deleted TINYINT NOT NULL DEFAULT 0,
    created_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_route_permission_path (route_path)
);

CREATE TABLE IF NOT EXISTS lerobot_saas_dev.sys_organization_route_permission (
    id VARCHAR(32) NOT NULL PRIMARY KEY,
    organization_id VARCHAR(32) NOT NULL,
    route_permission_id VARCHAR(32) NOT NULL,
    sort INT NOT NULL DEFAULT 0,
    deleted TINYINT NOT NULL DEFAULT 0,
    created_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_org_route_permission (organization_id, route_permission_id)
);

CREATE TABLE IF NOT EXISTS lerobot_saas_dev.sys_dataset (
    id VARCHAR(32) NOT NULL PRIMARY KEY,
    dataset_name VARCHAR(150) NOT NULL,
    organization_id VARCHAR(32) NOT NULL,
    user_id VARCHAR(32) NOT NULL,
    original_file_name VARCHAR(255) NOT NULL,
    storage_path VARCHAR(500) NOT NULL,
    upload_status VARCHAR(32) NOT NULL,
    error_message VARCHAR(500) NULL,
    codebase_version VARCHAR(50) NULL,
    robot_type VARCHAR(100) NULL,
    total_episodes INT NULL,
    total_frames BIGINT NULL,
    total_tasks INT NULL,
    fps INT NULL,
    data_files_size_mb DECIMAL(10,2) NULL,
    video_files_size_mb DECIMAL(10,2) NULL,
    feature_count INT NULL,
    camera_count INT NULL,
    feature_keys TEXT NULL,
    camera_keys TEXT NULL,
    metadata_json LONGTEXT NULL,
    sort INT NOT NULL DEFAULT 0,
    deleted TINYINT NOT NULL DEFAULT 0,
    created_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lerobot_saas_dev.sys_model (
    id VARCHAR(32) NOT NULL PRIMARY KEY,
    model_code VARCHAR(100) NOT NULL,
    model_name VARCHAR(150) NOT NULL,
    sort INT NOT NULL DEFAULT 0,
    deleted TINYINT NOT NULL DEFAULT 0,
    created_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lerobot_saas_test.sys_organization LIKE lerobot_saas_dev.sys_organization;
CREATE TABLE IF NOT EXISTS lerobot_saas_test.sys_icon LIKE lerobot_saas_dev.sys_icon;
CREATE TABLE IF NOT EXISTS lerobot_saas_test.sys_user LIKE lerobot_saas_dev.sys_user;
CREATE TABLE IF NOT EXISTS lerobot_saas_test.sys_route_permission LIKE lerobot_saas_dev.sys_route_permission;
CREATE TABLE IF NOT EXISTS lerobot_saas_test.sys_organization_route_permission LIKE lerobot_saas_dev.sys_organization_route_permission;
CREATE TABLE IF NOT EXISTS lerobot_saas_test.sys_dataset LIKE lerobot_saas_dev.sys_dataset;
CREATE TABLE IF NOT EXISTS lerobot_saas_test.sys_model LIKE lerobot_saas_dev.sys_model;

INSERT INTO lerobot_saas_dev.sys_organization (id, organization_name, organization_code, description, sort, deleted, created_time, updated_time)
VALUES ('1910000000000000001', 'Aloha', 'ALOHA', '默认组织', 0, 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE
organization_name = VALUES(organization_name),
organization_code = VALUES(organization_code),
description = VALUES(description),
sort = VALUES(sort),
deleted = VALUES(deleted),
updated_time = NOW();

INSERT INTO lerobot_saas_test.sys_organization (id, organization_name, organization_code, description, sort, deleted, created_time, updated_time)
VALUES ('1910000000000000001', 'Aloha', 'ALOHA', '默认组织', 0, 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE
organization_name = VALUES(organization_name),
organization_code = VALUES(organization_code),
description = VALUES(description),
sort = VALUES(sort),
deleted = VALUES(deleted),
updated_time = NOW();

INSERT INTO lerobot_saas_dev.sys_icon (id, icon_name, component_name, description, sort, deleted, created_time, updated_time) VALUES
('1910000000000000101', 'User', 'User', '用户头像', 1, 0, NOW(), NOW()),
('1910000000000000102', 'Avatar', 'Avatar', '头像图标', 2, 0, NOW(), NOW()),
('1910000000000000103', 'Star', 'Star', '星标图标', 3, 0, NOW(), NOW()),
('1910000000000000104', 'Medal', 'Medal', '勋章图标', 4, 0, NOW(), NOW()),
('1910000000000000105', 'Trophy', 'Trophy', '奖杯图标', 5, 0, NOW(), NOW()),
('1910000000000000106', 'Bell', 'Bell', '铃铛图标', 6, 0, NOW(), NOW()),
('1910000000000000107', 'Cherry', 'Cherry', '樱桃图标', 7, 0, NOW(), NOW()),
('1910000000000000108', 'MagicStick', 'MagicStick', '魔法棒图标', 8, 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE
icon_name = VALUES(icon_name),
component_name = VALUES(component_name),
description = VALUES(description),
sort = VALUES(sort),
deleted = VALUES(deleted),
updated_time = NOW();

INSERT INTO lerobot_saas_test.sys_icon (id, icon_name, component_name, description, sort, deleted, created_time, updated_time) VALUES
('1910000000000000101', 'User', 'User', '用户头像', 1, 0, NOW(), NOW()),
('1910000000000000102', 'Avatar', 'Avatar', '头像图标', 2, 0, NOW(), NOW()),
('1910000000000000103', 'Star', 'Star', '星标图标', 3, 0, NOW(), NOW()),
('1910000000000000104', 'Medal', 'Medal', '勋章图标', 4, 0, NOW(), NOW()),
('1910000000000000105', 'Trophy', 'Trophy', '奖杯图标', 5, 0, NOW(), NOW()),
('1910000000000000106', 'Bell', 'Bell', '铃铛图标', 6, 0, NOW(), NOW()),
('1910000000000000107', 'Cherry', 'Cherry', '樱桃图标', 7, 0, NOW(), NOW()),
('1910000000000000108', 'MagicStick', 'MagicStick', '魔法棒图标', 8, 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE
icon_name = VALUES(icon_name),
component_name = VALUES(component_name),
description = VALUES(description),
sort = VALUES(sort),
deleted = VALUES(deleted),
updated_time = NOW();

INSERT INTO lerobot_saas_dev.sys_route_permission (id, route_name, route_path, component_path, title, icon, admin_only, sort, deleted, created_time, updated_time) VALUES
('1910000000000000011', 'home', '/', 'views/home/HomeView', '平台首页', 'House', 0, 1, 0, NOW(), NOW()),
('1910000000000000012', 'organizations', '/organizations', 'views/organization/OrganizationView', '组织管理', 'OfficeBuilding', 0, 2, 0, NOW(), NOW()),
('1910000000000000013', 'route-permissions', '/route-permissions', 'views/permission/RoutePermissionView', '页面权限', 'Menu', 0, 3, 0, NOW(), NOW()),
('1910000000000000014', 'permission-assign', '/permission-assign', 'views/permission/PermissionAssignView', '组织赋权', 'Checked', 0, 4, 0, NOW(), NOW()),
('1910000000000000015', 'profile', '/profile', 'views/profile/ProfileView', '个人中心', 'User', 0, 5, 0, NOW(), NOW()),
('1910000000000000017', 'dataset-upload', '/datasets', 'views/dataset/DatasetUploadView', '数据集上传', 'UploadFilled', 0, 6, 0, NOW(), NOW()),
('1910000000000000018', 'model-management', '/models', 'views/model/ModelManagementView', '模型管理', 'Cpu', 1, 7, 0, NOW(), NOW()),
('1910000000000000016', 'user-management', '/user-management', 'views/user/UserManagementView', '用户管理', 'UserFilled', 1, 90, 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE
route_name = VALUES(route_name),
route_path = VALUES(route_path),
component_path = VALUES(component_path),
title = VALUES(title),
icon = VALUES(icon),
admin_only = VALUES(admin_only),
sort = VALUES(sort),
deleted = VALUES(deleted),
updated_time = NOW();

INSERT INTO lerobot_saas_test.sys_route_permission (id, route_name, route_path, component_path, title, icon, admin_only, sort, deleted, created_time, updated_time) VALUES
('1910000000000000011', 'home', '/', 'views/home/HomeView', '平台首页', 'House', 0, 1, 0, NOW(), NOW()),
('1910000000000000012', 'organizations', '/organizations', 'views/organization/OrganizationView', '组织管理', 'OfficeBuilding', 0, 2, 0, NOW(), NOW()),
('1910000000000000013', 'route-permissions', '/route-permissions', 'views/permission/RoutePermissionView', '页面权限', 'Menu', 0, 3, 0, NOW(), NOW()),
('1910000000000000014', 'permission-assign', '/permission-assign', 'views/permission/PermissionAssignView', '组织赋权', 'Checked', 0, 4, 0, NOW(), NOW()),
('1910000000000000015', 'profile', '/profile', 'views/profile/ProfileView', '个人中心', 'User', 0, 5, 0, NOW(), NOW()),
('1910000000000000017', 'dataset-upload', '/datasets', 'views/dataset/DatasetUploadView', '数据集上传', 'UploadFilled', 0, 6, 0, NOW(), NOW()),
('1910000000000000018', 'model-management', '/models', 'views/model/ModelManagementView', '模型管理', 'Cpu', 1, 7, 0, NOW(), NOW()),
('1910000000000000016', 'user-management', '/user-management', 'views/user/UserManagementView', '用户管理', 'UserFilled', 1, 90, 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE
route_name = VALUES(route_name),
route_path = VALUES(route_path),
component_path = VALUES(component_path),
title = VALUES(title),
icon = VALUES(icon),
admin_only = VALUES(admin_only),
sort = VALUES(sort),
deleted = VALUES(deleted),
updated_time = NOW();

INSERT INTO lerobot_saas_dev.sys_user (id, name, gender, organization_id, email, password_hash, raw_password, avatar_icon_id, system_admin, sort, deleted, created_time, updated_time)
VALUES ('1910000000000000002', '王竞一', 1, '1910000000000000001', '632084210@qq.com', 'a0$.RJ5tRe2bkUEIhxRmRqSsOgsWrtFtvTexAjiSgncXz3..HGYaDXVC', 'Admin@123456', '1910000000000000102', 1, 0, 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE
name = VALUES(name),
gender = VALUES(gender),
organization_id = VALUES(organization_id),
email = VALUES(email),
password_hash = VALUES(password_hash),
raw_password = VALUES(raw_password),
avatar_icon_id = VALUES(avatar_icon_id),
system_admin = VALUES(system_admin),
sort = VALUES(sort),
deleted = VALUES(deleted),
updated_time = NOW();

INSERT INTO lerobot_saas_test.sys_user (id, name, gender, organization_id, email, password_hash, raw_password, avatar_icon_id, system_admin, sort, deleted, created_time, updated_time)
VALUES ('1910000000000000002', '王竞一', 1, '1910000000000000001', '632084210@qq.com', 'a0$.RJ5tRe2bkUEIhxRmRqSsOgsWrtFtvTexAjiSgncXz3..HGYaDXVC', 'Admin@123456', '1910000000000000102', 1, 0, 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE
name = VALUES(name),
gender = VALUES(gender),
organization_id = VALUES(organization_id),
email = VALUES(email),
password_hash = VALUES(password_hash),
raw_password = VALUES(raw_password),
avatar_icon_id = VALUES(avatar_icon_id),
system_admin = VALUES(system_admin),
sort = VALUES(sort),
deleted = VALUES(deleted),
updated_time = NOW();

INSERT INTO lerobot_saas_dev.sys_organization_route_permission (id, organization_id, route_permission_id, sort, deleted, created_time, updated_time) VALUES
(REPLACE(UUID(), '-', ''), '1910000000000000001', '1910000000000000011', 0, 0, NOW(), NOW()),
(REPLACE(UUID(), '-', ''), '1910000000000000001', '1910000000000000012', 0, 0, NOW(), NOW()),
(REPLACE(UUID(), '-', ''), '1910000000000000001', '1910000000000000013', 0, 0, NOW(), NOW()),
(REPLACE(UUID(), '-', ''), '1910000000000000001', '1910000000000000014', 0, 0, NOW(), NOW()),
(REPLACE(UUID(), '-', ''), '1910000000000000001', '1910000000000000015', 0, 0, NOW(), NOW()),
(REPLACE(UUID(), '-', ''), '1910000000000000001', '1910000000000000017', 0, 0, NOW(), NOW()),
(REPLACE(UUID(), '-', ''), '1910000000000000001', '1910000000000000018', 0, 0, NOW(), NOW()),
(REPLACE(UUID(), '-', ''), '1910000000000000001', '1910000000000000016', 0, 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE
sort = VALUES(sort),
deleted = VALUES(deleted),
updated_time = NOW();

INSERT INTO lerobot_saas_test.sys_organization_route_permission (id, organization_id, route_permission_id, sort, deleted, created_time, updated_time) VALUES
(REPLACE(UUID(), '-', ''), '1910000000000000001', '1910000000000000011', 0, 0, NOW(), NOW()),
(REPLACE(UUID(), '-', ''), '1910000000000000001', '1910000000000000012', 0, 0, NOW(), NOW()),
(REPLACE(UUID(), '-', ''), '1910000000000000001', '1910000000000000013', 0, 0, NOW(), NOW()),
(REPLACE(UUID(), '-', ''), '1910000000000000001', '1910000000000000014', 0, 0, NOW(), NOW()),
(REPLACE(UUID(), '-', ''), '1910000000000000001', '1910000000000000015', 0, 0, NOW(), NOW()),
(REPLACE(UUID(), '-', ''), '1910000000000000001', '1910000000000000017', 0, 0, NOW(), NOW()),
(REPLACE(UUID(), '-', ''), '1910000000000000001', '1910000000000000018', 0, 0, NOW(), NOW()),
(REPLACE(UUID(), '-', ''), '1910000000000000001', '1910000000000000016', 0, 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE
sort = VALUES(sort),
deleted = VALUES(deleted),
updated_time = NOW();
