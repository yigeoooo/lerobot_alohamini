package com.lerobot.saas.icon.service.impl;

import com.lerobot.saas.icon.dao.IconDao;
import com.lerobot.saas.icon.entity.SysIcon;
import com.lerobot.saas.icon.service.IconService;
import java.util.List;
import org.springframework.stereotype.Service;

@Service
public class IconServiceImpl implements IconService {

    private final IconDao iconDao;

    public IconServiceImpl(IconDao iconDao) {
        this.iconDao = iconDao;
    }

    @Override
    public List<SysIcon> listIcons() {
        return iconDao.selectAllIcons();
    }
}
