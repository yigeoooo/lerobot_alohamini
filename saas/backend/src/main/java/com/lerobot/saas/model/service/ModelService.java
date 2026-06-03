package com.lerobot.saas.model.service;

import com.lerobot.saas.model.dto.ModelSaveRequest;
import com.lerobot.saas.model.vo.ModelVO;
import com.lerobot.saas.model.vo.PolicyDirectoryVO;
import java.util.List;

public interface ModelService {

    List<PolicyDirectoryVO> listPolicyDirectories();

    List<ModelVO> listModels();

    void createModel(ModelSaveRequest request);

    void updateModel(String modelId, ModelSaveRequest request);

    void deleteModel(String modelId);
}
