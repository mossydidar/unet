#!/usr/bin/env python
''' 
----------------------------------------------------------------------------
Copyright 2017 Intel Nervana 
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

	 http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
----------------------------------------------------------------------------
''' 

'''
  UNET entirely written in Tensorflow

  There is a settings.py file which can be used to change the filenames and training parameters.
  This script loads the numpy arrays with the training and testing data.
  Future version should probably use a batch iterator so that the entire file doesn't have
  to be loaded into memory all at once.
  After training the UNet, the script outputs:
  	1. A trace file of the program execution - Useful for optimization
  	2. A file of the graph variables (we currently save just the variables not the entire model)
  	3. A numpy file with the model predictions based on the testing data. This can be compared
  	     with msks_test.npy to evaluate the model's peformance.

  Usage:  numactl -p 1 python unet_tensorflow.py

'''
from settings import *      # Custom settings for UNet / KNL
import numpy as np
from preprocessing import * # Custom scripts for preprocessing images

import tensorflow as tf
from tqdm import tqdm  # pip install tqdm

def create_unet(imgs_placeholder):
	'''
	TF UNET IMPLEMENTATION
	'''

	img_height = tf.shape(imgs_placeholder)[1]
	img_width = tf.shape(imgs_placeholder)[2]

	conv1 = tf.layers.conv2d(name='conv1a', inputs=imgs_placeholder, filters=32, kernel_size=[3, 3], activation=tf.nn.relu, padding='SAME')
	conv1 = tf.layers.conv2d(name='conv1b', inputs=conv1, filters=32, kernel_size=[3, 3], activation=tf.nn.relu, padding='SAME')
	pool1 = tf.layers.max_pooling2d(name='pool1', inputs=conv1, pool_size=[2,2], strides=2) # img = 64 x 64 if original size was 128 x 128

	conv2 = tf.layers.conv2d(name='conv2a', inputs=pool1, filters=64, kernel_size=[3, 3], activation=tf.nn.relu, padding='SAME')
	conv2 = tf.layers.conv2d(name='conv2b', inputs=conv2, filters=64, kernel_size=[3, 3], activation=tf.nn.relu, padding='SAME')
	pool2 = tf.layers.max_pooling2d(name='pool2', inputs=conv2, pool_size=[2, 2], strides=2) # img = 32 x 32 if original size was 128 x 128

	conv3 = tf.layers.conv2d(name='conv3a', inputs=pool2, filters=128, kernel_size=[3, 3], activation=tf.nn.relu, padding='SAME')
	conv3 = tf.layers.conv2d(name='conv3b', inputs=conv3, filters=128, kernel_size=[3, 3], activation=tf.nn.relu, padding='SAME')
	pool3 = tf.layers.max_pooling2d(name='pool3', inputs=conv3, pool_size=[2, 2], strides=2) # img = 16 x 16 if original size was 128 x 128

	conv4 = tf.layers.conv2d(name='conv4a', inputs=pool3, filters=256, kernel_size=[3, 3], activation=tf.nn.relu, padding='SAME')
	conv4 = tf.layers.conv2d(name='conv4b', inputs=conv4, filters=256, kernel_size=[3, 3], activation=tf.nn.relu, padding='SAME')
	pool4 = tf.layers.max_pooling2d(name='pool4', inputs=conv4, pool_size=[2, 2], strides=2) #img = 8 x 8 if original size was 128 x 128

	conv5 = tf.layers.conv2d(name='conv5a', inputs=pool4, filters=512, kernel_size=[3, 3], activation=tf.nn.relu, padding='SAME')
	conv5 = tf.layers.conv2d(name='conv5b', inputs=conv5, filters=512, kernel_size=[3, 3], activation=tf.nn.relu, padding='SAME')

	up6 = tf.concat([tf.image.resize_nearest_neighbor(conv5, (img_height//8, img_width//8)), conv4], -1, name='up6')
	conv6 = tf.layers.conv2d(name='conv6a', inputs=up6, filters=256, kernel_size=[3,3], activation=tf.nn.relu, padding='SAME')
	conv6 = tf.layers.conv2d(name='conv6b', inputs=conv6, filters=256, kernel_size=[3,3], activation=tf.nn.relu, padding='SAME')

	up7 = tf.concat([tf.image.resize_nearest_neighbor(conv6, (img_height//4, img_width//4)), conv3], -1, name='up7')
	conv7 = tf.layers.conv2d(name='conv7a', inputs=up7, filters=128, kernel_size=[3, 3], activation=tf.nn.relu, padding='SAME')
	conv7 = tf.layers.conv2d(name='conv7b', inputs=conv7, filters=128, kernel_size=[3,3], activation=tf.nn.relu, padding='SAME')

	up8 = tf.concat([tf.image.resize_nearest_neighbor(conv7, (img_height//2, img_width//2)), conv2], -1, name='up8')
	conv8 = tf.layers.conv2d(name='conv8a', inputs=up8, filters=64, kernel_size=[3, 3], activation=tf.nn.relu, padding='SAME')
	conv8 = tf.nn.dropout(conv8, 0.5)
	conv8 = tf.layers.conv2d(name='conv8b', inputs=conv8, filters=64, kernel_size=[3, 3], activation=tf.nn.relu, padding='SAME')

	up9 = tf.concat([tf.image.resize_nearest_neighbor(conv8, (img_height, img_width)), conv1], -1, name='up9')
	conv9 = tf.layers.conv2d(name='conv9a', inputs=up9, filters=32, kernel_size=[3, 3], activation=tf.nn.relu, padding='SAME')
	conv9 = tf.nn.dropout(conv9, 0.5)
	conv9 = tf.layers.conv2d(name='conv9b', inputs=conv1, filters=32, kernel_size=[3, 3], activation=tf.nn.relu, padding='SAME')

	pred_msk = tf.layers.conv2d(name='prediction_mask_loss', inputs=conv9, filters=1, kernel_size=[1,1], activation=None, padding='SAME')

	out_msk = tf.nn.sigmoid(pred_msk)

	return pred_msk, out_msk

def dice_coefficient(y_pred, y_true):
    '''
    Returns Dice coefficient
    2 * intersection / union

    '''
    smoothing = 1e-7

    y_pred_bool = tf.round(y_pred)

    intersection = tf.reduce_sum(y_pred_bool * y_true, axis=[1, 2, 3]) + smoothing
    
    # Sorensen Dice
    denominator = tf.reduce_sum(y_pred_bool, axis=[1, 2, 3]) + tf.reduce_sum(y_true, axis=[1, 2, 3]) + smoothing

    # Jaccard Dice
    #denominator = tf.reduce_sum(y_pred*y_pred, axis=[1, 2, 3]) + tf.reduce_sum(y_true*y_true, axis=[1, 2, 3]) + smoothing

    return tf.reduce_mean(2. * intersection / denominator)


def SaveTraceTimeline(run_metadata, **settings):
	'''
	Save the program execution trace timeline.
	To load this, open the Chrome browser and type 'chrome://tracing' in the url bar.
	Then click the "Load" button to load this json file of the trace.
	'''

	from tensorflow.python.client import timeline

	fetched_timeline = timeline.Timeline(run_metadata.step_stats)
	chrome_trace = fetched_timeline.generate_chrome_trace_format()
	with open(settings['timeline_filename'], 'w') as f:
		f.write(chrome_trace)
		print('Wrote trace file {}'.format(settings['timeline_filename']))


def SavePredictionsFile(test_preds, *settings):
	
	np.save(settings['predictions file'], test_preds)
	print('Test set segmentation masks saved to {}'.format(settings['predictions file']))

'''
BEGIN Main Script
'''
if __name__ =="__main__":


	# Load data from Numpy files
	imgs_file_train, msks_file_train, imgs_file_test, msks_file_test = LoadandPreprocessData(**settings)
	
	# Create Tensorflow placeholders for the data
	imgs_placeholder, msks_placeholder = CreatePlaceholder(imgs_file_train, msks_file_train)

	# Create UNet model in Tensorflow graph
	pred_msk, out_msk = create_unet(imgs_placeholder)

	loss = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(labels=msks_placeholder, logits=pred_msk))
	dice_cost = dice_coefficient(out_msk, msks_placeholder)

	# train_step = tf.train.GradientDescentOptimizer(0.5).minimize(loss)
	train_step = tf.train.AdamOptimizer().minimize(loss)

	# Add ops to save and restore all the variables.
	saver = tf.train.Saver()

	# Initialize all variables
	init_op = tf.global_variables_initializer()

	# Create a trace for the graph execution so that we can evaluate for optimizations
	options = tf.RunOptions(trace_level=tf.RunOptions.FULL_TRACE)
	run_metadata = tf.RunMetadata()

	# Create new TF session
	sess = tf.Session(config=tf.ConfigProto(
			intra_op_parallelism_threads=settings['omp_threads'], 
			inter_op_parallelism_threads=settings['intra_threads']))

	# Start training
	with sess.as_default():

		sess.run(init_op, options=options, run_metadata=run_metadata)

		if settings['USE_SAVED_MODEL']:
			try:
				saver.restore(sess, settings['savedModelWeightsFileName'])
				print('Restoring weights from previously-saved file: {}'.format(settings['savedModelWeightsFileName']))
			except:
				print('No saved weights file to load [{}].'.format(settings['savedModelWeightsFileName']))

		last_loss = float('inf') # Initialize to infinity
		num_samples = imgs_file_train.shape[0]

		print('Batch shape = {}, Iterations per epoch = {}'.format(imgs_file_train[0:(settings['batch_size'])].shape, 
			num_samples//settings['batch_size']))
		
		# Fit all training data
		for epoch in range(settings['training_epochs']):

			for idx in tqdm(range(0, num_samples - settings['batch_size'], settings['batch_size']), 
				desc='Epoch {} of {}'.format(epoch+1, settings['training_epochs'])):

				sess.run(train_step, feed_dict={imgs_placeholder: imgs_file_train[idx:(idx+settings['batch_size'])], 
					msks_placeholder: msks_file_train[idx:(idx+settings['batch_size'])]})
				
			# Handle partial batches (if num_samples is not evenly divisible by batch_size)
			if (num_samples%settings['batch_size']) > 0:
				sess.run(train_step, feed_dict={imgs_placeholder: imgs_file_train[idx:(idx+(num_samples%settings['batch_size']))], 
					msks_placeholder: msks_file_train[idx:(idx+(num_samples%settings['batch_size']))]})
				
			# Display logs per epoch step
			if (epoch+1) % settings['display_step'] == 0:
	
				loss_test, dice_test = sess.run([loss, dice_cost], feed_dict={imgs_placeholder: imgs_file_test, 
					msks_placeholder: msks_file_test})
				
				print('Epoch: {}, test loss = {:.6f}, Dice coefficient = {:.6f}'.format(epoch+1, loss_test, dice_test))

				'''
				Save the model if it is an improvement otherwise skip saving
				'''
				if loss_test < last_loss:
					last_loss = loss_test
					# Save the variables to disk.
					save_path = saver.save(sess, settings['savedModelWeightsFileName'])
					print('UNet Model weights saved in file: {}'.format(save_path))

		# Save the program execution trace.
		SaveTraceTimeline(run_metadata, **settings)

		# Make prediction segmentation masks based on the test data
		print('Predicting segmentation masks for test set')
		test_preds = sess.run(out_msk, feed_dict={imgs_placeholder: imgs_file_test})
		SavePredictionsFile(test_preds, *settings)

		print('Training finished.')

	
	




