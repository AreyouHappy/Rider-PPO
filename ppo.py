"""
Copyright (c) <2018> YoongiKim

 See the file license.txt for copying permission.
"""

import os
import shutil
import time
from time import sleep

from ppo.renderthread import RenderThread
from ppo.models import *
from ppo.trainer import Trainer
from agents import GymEnvironment
import time

# ## Proximal Policy Optimization (PPO)
# Contains an implementation of PPO as described [here](https://arxiv.org/abs/1707.06347).

# Algorithm parameters
# batch-size=<n>           How many experiences per gradient descent update step [default: 64].
batch_size = 256
# beta=<n>                 Strength of entropy regularization [default: 2.5e-3].
beta = 1e-1
# buffer-size=<n>          How large the experience buffer should be before gradient descent [default: 2048].
buffer_size = 256
# epsilon=<n>              Acceptable threshold around ratio of old and new policy probabilities [default: 0.2].
epsilon = 0.2
# gamma=<n>                Reward discount rate [default: 0.99].
gamma = 0.99
# hidden-units=<n>         Number of units in hidden layer [default: 64].
hidden_units = 256
# lambd=<n>                Lambda parameter for GAE [default: 0.95].
lambd = 0.95
# learning-rate=<rate>     Model learning rate [default: 3e-4].
learning_rate = 0.00001
# max-steps=<n>            Maximum number of steps to run environment [default: 1e6].
max_steps = 1e6
# normalize                Activate state normalization for this many steps and freeze statistics afterwards.
normalize_steps = 0
# num-epoch=<n>            Number of gradient descent steps per batch of experiences [default: 5].
num_epoch = 5
# num-layers=<n>           Number of hidden layers between state/observation and outputs [default: 2].
num_layers = 8
# time-horizon=<n>         How many steps to collect per agent before adding to buffer [default: 2048].
time_horizon = 4096

# General parameters
# keep-checkpoints=<n>     How many model checkpoints to keep [default: 5].
keep_checkpoints = 10
# load                     Whether to load the model or randomly initialize [default: False].
load_model = False
# run-path=<path>          The sub-directory name for model and summary statistics.
summary_path = './PPO_summary/{}x{}'.format(hidden_units, num_layers)
model_path = './models/{}x{}'.format(hidden_units, num_layers)
# summary-freq=<n>         Frequency at which to save training statistics [default: 10000].
summary_freq = 50
# save-freq=<n>            Frequency at which to save model [default: 50000].
save_freq = 5000
# train                    Whether to train model, or only run inference [default: False].
train_model = True
# render environment to display progress
render = False
# save recordings of episodes
record = False

#os.environ["CUDA_VISIBLE_DEVICES"] = "-1"  # GPU is not efficient here

env_name = 'Rider-v0'
env = GymEnvironment(env_name=env_name, log_path="./PPO_log", skip_frames=0)
env_render = GymEnvironment(env_name=env_name, log_path="./PPO_log_render", render=True, record=record)
fps = 30

print(str(env))
brain_name = env.external_brain_names[0]

tf.reset_default_graph()

ppo_model = create_agent_model(env, lr=learning_rate,
                               h_size=hidden_units, epsilon=epsilon,
                               beta=beta, max_step=max_steps,
                               normalize=normalize_steps, num_layers=num_layers)

is_continuous = env.brains[brain_name].action_space_type == "continuous"
use_observations = False
use_states = True

if not load_model:
    shutil.rmtree(summary_path, ignore_errors=True)

if not os.path.exists(model_path):
    os.makedirs(model_path)

if not os.path.exists(summary_path):
    os.makedirs(summary_path)

tf.set_random_seed(np.random.randint(1024))
init = tf.global_variables_initializer()
saver = tf.train.Saver(max_to_keep=keep_checkpoints)

with tf.Session() as sess:
    # Instantiate model parameters
    if load_model:
        print('Loading Model...')
        ckpt = tf.train.get_checkpoint_state(model_path)
        if ckpt is None:
            print('The model {0} could not be found. Make sure you specified the right --run-path'.format(model_path))
        saver.restore(sess, ckpt.model_checkpoint_path)
    else:
        sess.run(init)

    steps, last_reward = sess.run([ppo_model.global_step, ppo_model.last_reward])
    summary_writer = tf.summary.FileWriter(summary_path)
    info = env.reset()[brain_name]
    trainer = Trainer(ppo_model, sess, info, is_continuous, use_observations, use_states, train_model)
    trainer_monitor = Trainer(ppo_model, sess, info, is_continuous, use_observations, use_states, False)
    render_started = False

    while steps <= max_steps or not train_model:
        #print('step: {}'.format(steps))
        if env.global_done:
            info = env.reset()[brain_name]
            trainer.reset_buffers(info, total=True)
        # Decide and take an action
        if train_model:
            info = trainer.take_action(info, env, brain_name, steps, normalize_steps, stochastic=True)
            trainer.process_experiences(info, time_horizon, gamma, lambd)
        else:
            sleep(1)
        if len(trainer.training_buffer['actions']) > buffer_size and train_model:
            if render:
                renderthread.pause()
            print("Optimizing...")
            t = time.time()
            # Perform gradient descent with experience buffer
            trainer.update_model(batch_size, num_epoch)
            print("Optimization finished in {:.1f} seconds.".format(float(time.time() - t)))
            if render:
                renderthread.resume()
        if steps % summary_freq == 0 and steps != 0 and train_model:
            # Write training statistics to tensorboard.
            trainer.write_summary(summary_writer, steps)
        if steps % save_freq == 0 and steps != 0 and train_model:
            # Save Tensorflow model
            save_model(sess=sess, model_path=model_path, steps=steps, saver=saver)
        if train_model:
            steps += 1
            sess.run(ppo_model.increment_step)
            if len(trainer.stats['cumulative_reward']) > 0:
                mean_reward = np.mean(trainer.stats['cumulative_reward'])
                sess.run(ppo_model.update_reward, feed_dict={ppo_model.new_reward: mean_reward})
                last_reward = sess.run(ppo_model.last_reward)
        if not render_started and render:
            renderthread = RenderThread(sess=sess, trainer=trainer_monitor,
                                        environment=env_render, brain_name=brain_name, normalize=normalize_steps, fps=fps)
            renderthread.start()
            render_started = True
    # Final save Tensorflow model
    if steps != 0 and train_model:
        save_model(sess=sess, model_path=model_path, steps=steps, saver=saver)
env.close()
export_graph(model_path, env_name)
#os.system("shutdown")

