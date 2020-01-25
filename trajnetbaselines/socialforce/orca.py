import numpy as np
from scipy.interpolate import interp1d

import trajnettools

import rvo2

MAX_SPEED_MULTIPLIER = 1.3 # with respect to initial speed

def predict(input_paths, dest_dict=None, dest_type='true', orca_params=None, predict_all=False):

    def init_states(input_paths, sim, start_frame, dest_dict, dest_type):
        initial_state = []
        positions, goals, speed = [], [], []
        for i, _ in enumerate(input_paths):
            path = input_paths[i]
            ped_id = path[0].pedestrian
            past_path = [t for t in path if t.frame <= start_frame]
            future_path = [t for t in path if t.frame > start_frame]
            past_frames = [t.frame for t in path if t.frame <= start_frame]
            len_path = len(past_path)

            ## To consider agent or not consider.
            if (start_frame in past_frames) and len_path >= 4:
                curr = past_path[-1]
                prev = past_path[-4]

                ## Velocity
                curr_vel, curr_speed = vel_state(prev, curr, 3)
                max_speed = MAX_SPEED_MULTIPLIER * curr_speed

                ## Destination
                if dest_type == 'true':
                    if dest_dict is not None:
                        [d_x, d_y] = dest_dict[ped_id] 
                    else: 
                        raise ValueError
                elif dest_type == 'interp':
                    [d_x, d_y] = dest_state(past_path, len_path-1)
                elif dest_type == 'pred_end':
                    [d_x, d_y] = [future_path[-1].x, future_path[-1].y]
                else:
                    raise NotImplementedError

                positions.append((curr.x, curr.y))
                speed.append((curr_speed))
                goals.append((d_x, d_y))

                sim.addAgent((curr.x, curr.y), maxSpeed=max_speed, velocity=tuple(curr_vel))

        trajectories = [[positions[i]] for i in range(len(positions))]
        return trajectories, positions, goals, speed

    def vel_state(prev, curr, stride):
        diff = np.array([curr.x - prev.x, curr.y - prev.y])
        theta = np.arctan2(diff[1], diff[0])
        speed = np.linalg.norm(diff) / (stride * 0.4)
        return [speed*np.cos(theta), speed*np.sin(theta)], speed

    def dest_state(path, stride):
        x = [t.x for t in path]
        y = [t.y for t in path]
        time = list(range(stride+1))
        f = interp1d(x=time, y=[x, y], fill_value='extrapolate')
        return f(time[-1] + 12)

    multimodal_outputs = {}
    primary = input_paths[0]
    neighbours_tracks = []
    frame_diff = primary[1].frame - primary[0].frame
    start_frame = primary[8].frame
    first_frame = primary[8].frame + frame_diff

    fps = 20
    sampling_rate = fps / 2.5

    ## orca_params = [nDist, nReact, radius]

    ## Parameters              freq          nD        obD       nR        oR     rad       max.spd
    sim = rvo2.PyRVOSimulator(1 / fps, orca_params[0], 10, orca_params[1], 5, orca_params[2], 1.5)

    # initialize
    trajectories, positions, goals, speed = init_states(input_paths, sim, start_frame, dest_dict, dest_type)
    
    num_ped = len(speed)
    count = 0
    end_range = 0.05
    ##Simulate a scene
    while count < sampling_rate * 12 + 1:
        count += 1
        sim.doStep()
        reaching_goal = []
        for i in range(num_ped):
            if count == 1:
                trajectories[i].pop(0)
            position = sim.getAgentPosition(i)

            if count % sampling_rate == 0:
                trajectories[i].append(position)

            # check if this agent reaches the goal
            if np.linalg.norm(np.array(position) - np.array(goals[i])) < end_range:
                sim.setAgentPrefVelocity(i, (0, 0))

            else:
            # Move towards goal
                velocity = np.array((goals[i][0] - position[0], goals[i][1] - position[1]))
                curr_speed = np.linalg.norm(velocity)
                pref_vel = speed[i] * velocity / curr_speed if curr_speed > speed[i] else velocity
                sim.setAgentPrefVelocity(i, tuple(pref_vel.tolist()))


    states = np.array(trajectories).transpose(1, 0, 2)

    # predictions
    for i in range(states.shape[1]):
        ped_id = input_paths[i][0].pedestrian
        if i == 0:
            primary_track = [trajnettools.TrackRow(first_frame + j * frame_diff, ped_id, x, y)
                             for j, (x, y) in enumerate(states[:, i, 0:2])]
        else:
            neighbours_tracks.append([trajnettools.TrackRow(first_frame + j * frame_diff, ped_id, x, y)
                                      for j, (x, y) in enumerate(states[:, i, 0:2])])

    ## Primary Prediction Only
    if not predict_all:
        neighbours_tracks = []

    # Unimodal Prediction
    multimodal_outputs[0] = primary_track, neighbours_tracks
    return multimodal_outputs
