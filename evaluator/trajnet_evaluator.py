import numpy as np
import trajnettools
import shutil
import os
import warnings
from collections import OrderedDict
import argparse

import evaluator.write as write
from evaluator.design_table import Table
from trajnetbaselines import kalman
from trajnetbaselines import socialforce

class TrajnetEvaluator:
    def __init__(self, reader_gt, scenes_gt, scenes_id_gt, scenes_sub, indexes):
        self.reader_gt = reader_gt
        
        ##Ground Truth
        self.scenes_gt = scenes_gt
        self.scenes_id_gt = scenes_id_gt

        ##Prediction
        self.scenes_sub = scenes_sub

        ## Dictionary of type of trajectories
        self.indexes = indexes

        ## The 4 types of Trajectories
        self.static_scenes = {'N': len(indexes[1])}
        self.linear_scenes = {'N': len(indexes[2])}
        self.forced_non_linear_scenes = {'N': len(indexes[3])}
        self.non_linear_scenes = {'N': len(indexes[4])}

        ## The 4 metrics ADE, FDE, ColI, ColII
        self.average_l2 = {'N': len(scenes_gt)}
        self.final_l2 = {'N': len(scenes_gt)}
        self.final_collision = {'N': len(scenes_gt)}

    def aggregate(self, name, disable_collision, kf=False):

        ## Overall Scores
        average = 0.0
        final = 0.0
        glob_collision = 0

        ## Aggregates ADE, FDE and Collision in GT & Pred for each category 
        score = {1: [0.0, 0.0, 0, 0, 0], 2: [0.0, 0.0, 0, 0, 0], 3: [0.0, 0.0, 0, 0, 0], 4: [0.0, 0.0, 0, 0, 0]}

        ## Number of future trajectories proposed by the model #Multimodality
        num_predictions = 0
        tmp_prediction = {}
        for track in self.scenes_sub[0][0]:
            if track.prediction_number and track.prediction_number > num_predictions:
                num_predictions = scene.prediction_number

        ## Max. 3 trajectories can only be outputted
        if num_predictions > 2:
            warnings.warn("3 predictions at most")
            num_predictions = 2

        ## Iterate
        for i in range(len(self.scenes_gt)):
            ground_truth = self.scenes_gt[i]

            ## Extract Prediction Frames
            primary_tracks = [t for t in self.scenes_sub[i][0] if t.scene_id == self.scenes_id_gt[i]]
            neighbours_tracks = [[t for t in self.scenes_sub[i][j] if t.scene_id == self.scenes_id_gt[i]] for j in range(1, len(self.scenes_sub[i]))]

            l2 = 1e10
            for np in range(num_predictions + 1):
                primary_prediction = [t for t in primary_tracks if t.prediction_number == np]
                tmp_score = trajnettools.metrics.final_l2(ground_truth[0], primary_prediction)
                if tmp_score < l2:      
                    best_prediction_number = np
                    l2 = tmp_score

            primary_tracks = [t for t in primary_tracks if t.prediction_number == best_prediction_number]
            neighbours_tracks = [[t for t in neighbours_tracks[j] if t.prediction_number == best_prediction_number] for j in range(len(neighbours_tracks))]

            frame_gt = [t.frame for t in ground_truth[0]][-12:]
            frame_pred = [t.frame for t in primary_tracks]

            ## To verify if same scene
            if frame_gt != frame_pred:
                raise Exception('frame numbers are not consistent')

            average_l2 = trajnettools.metrics.average_l2(ground_truth[0], primary_tracks)
            final_l2 = trajnettools.metrics.final_l2(ground_truth[0], primary_tracks)
            
            if not disable_collision:
                ## Collisions in GT
                for j in range(1, len(ground_truth)):
                    if trajnettools.metrics.collision(primary_tracks, ground_truth[j]):
                        glob_collision += 1
                        for key in list(score.keys()):
                            if self.scenes_id_gt[i] in self.indexes[key]:
                                score[key][2] += 1
                        break

                ## Collision in Predictions 
                flat_neigh_list = [item for sublist in neighbours_tracks for item in sublist]
                if len(flat_neigh_list): 
                    for key in list(score.keys()):
                        if self.scenes_id_gt[i] in self.indexes[key]:
                            score[key][4] += 1
                            for j in range(len(neighbours_tracks)):
                                if trajnettools.metrics.collision(primary_tracks, neighbours_tracks[j]):
                                    score[key][3] += 1
                                    break


            # aggregate FDE and ADE
            average += average_l2
            final += final_l2
            for key in list(score.keys()):
                if self.scenes_id_gt[i] in self.indexes[key]:
                    score[key][0] += average_l2
                    score[key][1] += final_l2

        ## Average ADE and FDE
        average /= len(self.scenes_gt)
        final /= len(self.scenes_gt)
        for key in list(score.keys()):
            if self.indexes[key]:
                score[key][0] /= len(self.indexes[key])
                score[key][1] /= len(self.indexes[key])

        ##Adding value to dict
        self.average_l2[name] = average
        self.final_l2[name] = final
        self.final_collision[name] = glob_collision

        self.static_scenes[name] = score[1]
        self.linear_scenes[name] = score[2]
        self.forced_non_linear_scenes[name] = score[3]
        self.non_linear_scenes[name] = score[4]

        return self

    def result(self):
        return self.average_l2, self.final_l2, self.static_scenes, self.linear_scenes, \
               self.forced_non_linear_scenes, self.non_linear_scenes, self.final_collision


def eval(gt, input_file, disable_collision, args):
    
    # Ground Truth
    reader_gt = trajnettools.Reader(gt, scene_type='paths')
    scenes_gt = [s for _, s in reader_gt.scenes()]
    scenes_id_gt = [s_id for s_id, _ in reader_gt.scenes()]

    # Scene Predictions
    reader_sub = trajnettools.Reader(input_file, scene_type='paths')
    scenes_sub = [s for _, s in reader_sub.scenes()]

    ## indexes is dictionary deciding which scenes are in which type
    indexes = {}
    for i in range(1,5):
        indexes[i] = []
    for scene in reader_gt.scenes_by_id:
        for ii in range(1, 5):
            if ii in reader_gt.scenes_by_id[scene].tag:
                indexes[ii].append(scene)


    # Evaluate
    evaluator = TrajnetEvaluator(reader_gt, scenes_gt, scenes_id_gt, scenes_sub, indexes)
    evaluator.aggregate('kf', disable_collision, kalman)
    return evaluator.result()

def main():

    parser = argparse.ArgumentParser()
    parser.add_argument('--data', default='syn_large_data', choices = ('data_ucy', 'syn_data', 'syn_large_data', 'syn_3_data', 'noisy_controlled', 'mix_synth'),
                        help='path of data')
    parser.add_argument('--output', required=True, nargs='+',
                        help='output folder')
    parser.add_argument('--disable-write', action='store_true',
                        help='disable writing new files')
    parser.add_argument('--disable-collision', action='store_true',
                        help='disable collision metric')
    parser.add_argument('--test', default = True)
    parser.add_argument('--test-path', default = 'test')
    args = parser.parse_args()

    ## Path to the data folder name to predict 
    args.data = 'DATA_BLOCK/' + args.data + '/'

    ## Test_pred : Folders for saving model predictions
    args.data = args.data + args.test_path + '_pred/'

    ## Writes to Test_pred
    ########## Does this overwrite existing predictions? No. ####################
    if not args.disable_write:
        write.main(args)

    ## Evaluates test_pred with test_private
    names = []
    for model in args.output:
        names.append(model.split('/')[-1].replace('.pkl', ''))

    # Initiate Result Table
    table = Table()
    

    for name in names:
        list_sub = sorted([f for f in os.listdir(args.data + name)
                           if not f.startswith('.')])

        submit_datasets = [args.data + name + '/' + f for f in list_sub]
        true_datasets = [args.data.replace('pred', 'private') + f for f in list_sub]
        print(name)

        ## Evaluate submitted datasets with True Datasets [The main eval function]
        results = {submit_datasets[i].replace(args.data, '').replace('.ndjson', ''):
                   eval(true_datasets[i], submit_datasets[i], args.disable_collision, args)
                   for i in range(len(true_datasets))}

        ## Saves results in dict
        table.add_entry(name, results)

    ## Make Result Table 
    table.print_table()
 
if __name__ == '__main__':
    main()
