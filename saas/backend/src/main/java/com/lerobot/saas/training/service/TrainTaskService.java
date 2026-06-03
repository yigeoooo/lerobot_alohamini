package com.lerobot.saas.training.service;

import com.lerobot.saas.training.dto.TrainTaskCreateRequest;
import com.lerobot.saas.training.vo.SavedModelVO;
import com.lerobot.saas.training.vo.TrainTaskVO;
import java.nio.file.Path;
import java.util.List;

public interface TrainTaskService {

    TrainTaskVO createTrainTask(TrainTaskCreateRequest request);

    List<TrainTaskVO> listCurrentUserTasks();

    String getTaskLog(String taskId);

    void stopTask(String taskId);

    List<SavedModelVO> listCurrentUserSavedModels();

    Path requireTaskDownloadPath(String taskId);

    Path requireSavedModelDownloadPath(String modelName);
}
