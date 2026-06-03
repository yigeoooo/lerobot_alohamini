package com.lerobot.saas.dataset.service;

import com.lerobot.saas.dataset.dto.DatasetRenameRequest;
import com.lerobot.saas.dataset.vo.DatasetVO;
import java.util.List;
import org.springframework.web.multipart.MultipartFile;

public interface DatasetService {

    DatasetVO uploadDataset(String datasetName, List<MultipartFile> files, List<String> relativePaths);

    List<DatasetVO> listCurrentUserDatasets();

    void renameDataset(String datasetId, DatasetRenameRequest request);

    void deleteDataset(String datasetId);
}
