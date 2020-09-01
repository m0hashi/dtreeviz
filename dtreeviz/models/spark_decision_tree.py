from abc import ABC
from collections import defaultdict
from typing import List, Mapping

import numpy as np

from dtreeviz.models.shadow_decision_tree import ShadowDecTree
from pyspark.ml.classification import DecisionTreeClassificationModel, DecisionTreeRegressionModel


class ShadowSparkTree(ShadowDecTree):

    def __init__(self, tree_model: (DecisionTreeClassificationModel, DecisionTreeRegressionModel),
                 x_data,
                 y_data,
                 feature_names: List[str] = None,
                 target_name: str = None,
                 class_names: (List[str], Mapping[int, str]) = None):

        self.tree_model = tree_model
        self.tree_nodes, self.children_left, self.children_right = self._get_nodes_info()
        self.features = None  # lazy initialization
        self.thresholds = None  # lazy initialization
        self.node_to_samples = None  # lazy initialization
        super().__init__(tree_model, x_data, y_data, feature_names, target_name, class_names)

    def _get_nodes_info(self):
        tree_nodes = [None] * self.tree_model.numNodes
        children_left = [-1] * self.tree_model.numNodes
        children_right = [-1] * self.tree_model.numNodes
        node_index = 0

        def recur(node, node_id):
            nonlocal node_index
            tree_nodes[node_id] = node
            if node.numDescendants() == 0:
                return
            else:
                node_index += 1
                children_left[node_id] = node_index
                recur(node.leftChild(), node_index)

                node_index += 1
                children_right[node_id] = node_index
                recur(node.rightChild(), node_index)

        recur(self.tree_model._call_java('rootNode'), 0)
        return tree_nodes, children_left, children_right

    def is_fit(self) -> bool:
        if isinstance(self.tree_model, (DecisionTreeClassificationModel, DecisionTreeRegressionModel)):
            return True
        return False

    def is_classifier(self) -> bool:
        return isinstance(self.tree_model, DecisionTreeClassificationModel)

    def is_categorical_split(self, id) -> bool:
        node = self.tree_nodes[id]
        if "InternalNode" in node.toString():
            if "CategoricalSplit" in node.split().toString():
                return True
        return False

    def get_class_weights(self):
        pass

    def get_class_weight(self):
        pass

    def get_thresholds(self) -> np.ndarray:
        if self.thresholds is not None:
            return self.thresholds

        node_thresholds = [-1] * self.nnodes()
        for i in range(self.nnodes()):
            node = self.tree_nodes[i]
            if "InternalNode" in node.toString():
                if "CategoricalSplit" in node.split().toString():
                    node_thresholds[i] = (list(node.split().leftCategories()), list(node.split().rightCategories()))
                elif "ContinuousSplit" in node.split().toString():
                    node_thresholds[i] = node.split().threshold()

        self.thresholds = np.array(node_thresholds)
        return self.thresholds

    def get_features(self) -> np.ndarray:
        if self.features is not None:
            return self.features

        feature_index = [-1] * self.tree_model.numNodes
        for i in range(self.tree_model.numNodes):
            if "InternalNode" in self.tree_nodes[i].toString():
                feature_index[i] = self.tree_nodes[i].split().featureIndex()
        self.features = np.array(feature_index)
        return self.features

    def criterion(self) -> str:
        return self.tree_model.getImpurity().upper()

    def nclasses(self) -> int:
        if not self.is_classifier():
            return 1
        return self.tree_model.numClasses

    # TODO
    # for this we need y_dataset to be specified, think how to solve it without specifing the y_data
    def classes(self) -> np.ndarray:
        if self.is_classifier():
            return np.unique(self.y_data)

    def get_node_samples(self):
        if self.node_to_samples is not None:
            return self.node_to_samples

        node_to_samples = defaultdict(list)
        for i in range(self.x_data.shape[0]):
            prediction, path = self.predict(self.x_data[i])
            for node in path:
                node_to_samples[node.id].append(i)

        self.node_to_samples = node_to_samples
        return self.node_to_samples

    def get_node_nsamples(self, id):
        return self.tree_nodes[id].impurityStats().rawCount()

    def get_children_left(self) -> np.ndarray:
        return np.array(self.children_left, dtype=int)

    def get_children_right(self):
        return np.array(self.children_right, dtype=int)

    def get_node_split(self, id) -> (int, float, list):
        return self.get_thresholds()[id]

    def get_node_feature(self, id) -> int:
        return self.get_features()[id]

    def get_node_nsamples_by_class(self, id):
        if self.is_classifier():
            return np.array(self.tree_nodes[id].impurityStats().stats())

    def get_prediction(self, id):
        return self.tree_nodes[id].prediction()

    def nnodes(self) -> int:
        return self.tree_model.numNodes

    def get_node_criterion(self, id):
        return self.tree_nodes[id].impurity()

    def get_feature_path_importance(self, node_list):
        pass

    def get_max_depth(self) -> int:
        return self.tree_model.getMaxDepth()

    def get_score(self) -> float:
        pass

    def get_min_samples_leaf(self) -> (int, float):
        return self.tree_model.getMinInstancesPerNode()

    def shouldGoLeftAtSplit(self, id, x):
        if self.is_categorical_split(id):
            return x in self.get_node_split(id)[0]
        return x < self.get_node_split(id)
