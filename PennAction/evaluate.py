from os import path as osp

from argparse import ArgumentParser
import tensorflow as tf
import numpy as np
from PIL import Image

import utils
from models import FinalModel
from data import SequenceDataLoader


def main():
    np.random.seed(1)
    parser = ArgumentParser()
    parser.add_argument('--config', type=str, required=True, help='path of the configuration file')
    parser.add_argument('--checkpoint_stage1', type=str, required=True, help='path of the stage1 checkpoint')
    parser.add_argument('--checkpoint_stage2', type=str, required=True, help='path of the stage2 checkpoint')
    parser.add_argument('--save_dir', type=str, required=False, help='root dir to save results', default='results/eval')
    args = parser.parse_args()

    config = utils.load_config(args.config)
    model_config = config['model']
    paths_config = config['paths']
    data_dir = paths_config['data_dir']
    n_points = model_config['n_pts']
    n_action = model_config['n_action']
    batch_size = 1

    session_config = tf.ConfigProto(allow_soft_placement=True, log_device_placement=False)
    session_config.gpu_options.allow_growth = True

    mse_list = []

    # directory setup

    if not _checkpoint_exist(args.checkpoint_stage1):
        raise Exception('checkpoint not found at %s' % args.checkpoint_stage1)

    if not _checkpoint_exist(args.checkpoint_stage1):
        raise Exception('checkpoint not found at %s' % args.checkpoint_stage2)

    # start session
    with tf.Session(config=session_config) as sess:
        # import dataset
        test_loader = SequenceDataLoader(data_dir, 'test',
                                         n_points=n_points, n_action=n_action,
                                         random_order=False,
                                         randomness=False,
                                         with_image_seq=True)
        test_dataset = test_loader.get_dataset(batch_size,
                                               repeat=False,
                                               shuffle=False,
                                               num_preprocess_threads=12)

        # setup inputs
        training_pl = tf.placeholder(tf.bool)
        handle_pl = tf.placeholder(tf.string, shape=[])
        base_iterator = tf.data.Iterator.from_string_handle(handle_pl, test_dataset.output_types,
                                                            test_dataset.output_shapes)
        inputs = base_iterator.get_next()

        # initializing models
        model = FinalModel(config)
        print('model initialized')
        model.build(inputs)

        # variables initialization
        tf.logging.set_verbosity(tf.logging.INFO)
        global_init = tf.global_variables_initializer()
        local_init = tf.local_variables_initializer()
        sess.run([global_init, local_init])

        # data iterator initialization
        test_iterator = test_dataset.make_initializable_iterator()
        test_handle = sess.run(test_iterator.string_handle())

        # checkpoint restoration
        model.restore(sess, args.checkpoint_stage1)
        model.restore(sess, args.checkpoint_stage2)

        # iterator initialization
        sess.run(test_iterator.initializer)

        # running on test dataset
        sample_idx = 0
        n_iters = utils.training.get_n_iterations(test_loader.length(), batch_size)
        feed_dict = {handle_pl: test_handle, training_pl: False}
        for j in range(n_iters):
            min_mse = 1.0
            for s in range(20):
                outputs = model.run(sess, feed_dict)
                cur_mse = np.mean(np.abs(outputs['fut_pt_raw'] - outputs['real_seq']))
                # print(j,s)
                import matplotlib.pyplot as plt
                import os
                if model.sth_pro:
                    for i in range(5):
                        plt.plot(np.array([_ for _ in range(1, 33)]), outputs['ref_seq'][0,i,:,0])
                    os.makedirs('./sample_test_ours/'+str(j), exist_ok = True)
                    plt.plot(np.array([_ for _ in range(1, 33)]), outputs['fut_pt_raw'][0,:,0], '*')
                    plt.plot(np.array([_ for _ in range(1, 33)]), outputs['real_seq'][0,:,0], 'o')
                    plt.plot(np.array([0]), outputs['first_pt'][0,0], 'o')
                    plt.savefig('./sample_test_ours/'+str(j)+'/'+str(s)+'.png')
                    plt.clf()
                else:
                    os.makedirs('./sample_test_vae/'+str(j), exist_ok = True)
                    plt.plot(outputs['fut_pt_raw'][0,:,0], '*')
                    plt.plot(outputs['real_seq'][0,:,0], 'o')
                    plt.savefig('./sample_test_vae/'+str(j)+'/'+str(s)+'.png')
                    plt.clf()

                if cur_mse < min_mse:
                    min_mse = cur_mse
                    # saving outputs
                    outputs_im = outputs['im']
                    outputs_real_im_seq = outputs['real_im_seq']
                    outputs_pred_im_seq = outputs['pred_im_seq']
                    # print(outputs['z'][0,:10])

                    outputs_mask = outputs['mask']
                    outputs_pred_im_crude = outputs['pred_im_crude']
                    outputs_current_points = outputs['current_points']
                    outputs_future_points = outputs['future_points']

                    batch_dim = outputs['im'].shape[0]
                    for batch_idx in range(batch_dim):
                        sample_save_dir = osp.join(args.save_dir, '%04d' % sample_idx)
                        utils.touch_dir(sample_save_dir)

                        _save_img(osp.join(sample_save_dir, 'input_im.png'),
                                outputs_im[batch_idx],
                                rescale=True)
                        _save_img(osp.join(sample_save_dir, 'current_points.png'),
                                outputs_current_points[batch_idx],
                                rescale=False)

                        _save_img_sequence(osp.join(sample_save_dir, 'real_seq'),
                                        outputs_real_im_seq[batch_idx],
                                        rescale=True)
                        _save_img_sequence(osp.join(sample_save_dir, 'pred_seq'),
                                        outputs_pred_im_seq[batch_idx],
                                        rescale=True)
                        _save_img_sequence(osp.join(sample_save_dir, 'mask'),
                                        outputs_mask[batch_idx],
                                        rescale=False)
                        _save_img_sequence(osp.join(sample_save_dir, 'crude'),
                                        outputs_pred_im_crude[batch_idx],
                                        rescale=False)
                        _save_img_sequence(osp.join(sample_save_dir, 'crude'),
                                        outputs_pred_im_crude[batch_idx],
                                        rescale=True)
                        _save_img_sequence(osp.join(sample_save_dir, 'pred_points'),
                                        outputs_future_points[batch_idx],
                                        rescale=False)

                        # next sample idx
                pass
            sample_idx += 1
            print(j, min_mse)
            pass
        print('iteration through test set finished')
    # return np.array(mse_list)
    pass

def _save_img(file_path, img, rescale=False):
    mode = None
    if img.shape[2] <= 2:
        img = np.squeeze(img, axis=2)
        mode = 'L'

    if rescale:
        img = 0.5 * (img + 1.0)

    img = (img * 255).astype(np.uint8)
    img = Image.fromarray(img, mode=mode)
    img.save(file_path)
    pass

def _save_img_sequence(output_dir, img_seq, rescale=False):
    utils.touch_dir(output_dir)

    for i in range(img_seq.shape[0]):
        _save_img(osp.join(output_dir, '%06d.png' % i), img_seq[i], rescale=rescale)
    pass

def _checkpoint_exist(checkpoint_path):
    return tf.gfile.Exists(checkpoint_path) or tf.gfile.Exists(checkpoint_path + '.index')


if __name__ == '__main__':
    main()
