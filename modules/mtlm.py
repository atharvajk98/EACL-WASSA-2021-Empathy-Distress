# File contatins Class for Mutli-task learning model 
# File: mtlm.py
# Author: Atharva Kulkarni

import sys
sys.path.append('../')

from utils.utils import Utils
import time
import numpy as np
from scipy.stats import pearsonr
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.utils import class_weight
from tensorflow.keras.layers import Input, Dense, Dropout, Concatenate, LeakyReLU, PReLU
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.regularizers import l2
from tensorflow.keras.callbacks import ModelCheckpoint, ReduceLROnPlateau, EarlyStopping
from tensorflow.keras.utils import plot_model
from tensorflow.keras.models import load_model
from tensorflow.keras import Model






class MTLM():


    # ------------------------------------------------------------ Constructor ------------------------------------------------------------
    
    def __init__(self, base_model_type="CNN", activation="relu", score_loss="mse", binary_loss="binary_crossentropy", multiclass_loss="sparse_categorical_crossentropy", cpkt="trial"):

        # Set the model activation:
        if activation == "leaky_relu":
            self.activation = LeakyReLU()
        elif activation == "paramaterized_leaky_relu":
            self.activation = PReLU()           
        elif activation == "relu":
            self.activation = "relu"
        else:
            self.activation = activation

        # Set the regression loss:
        self.score_metric = "mean_squared_error"
        if score_loss == "huber":
            self.score_loss = "huber_loss"
        elif score_loss == "log_cosh":
            self.score_loss = "log_cosh"
        elif score_loss == "mean_squared_logarithmic_error":
            self.score_loss = "mean_squared_logarithmic_error"
        else:
            self.score_loss = "mse"

        # Set the binary classification loss:
        if binary_loss == "hinge":
            self.binary_loss = "hinge"
            self.binary_activation = "tanh"
        elif binary_loss == "squared_hinge":
            self.binary_loss = "squared_hinge"
            self.binary_activation = "tanh"
        else:
            self.binary_loss = "binary_crossentropy"
            self.binary_activation = "sigmoid"

        # Set the multi-class calssification loss:
        if multiclass_loss == "kld":
            self.multiclass_loss = "kl_divergence"
        else:
            self.multiclass_loss = "sparse_categorical_crossentropy"

        self.base_model_type = base_model_type
        self.bert_models = ["BERT", "DistilBERT", "RoBERTa", "custom"]
        if self.base_model_type in self.bert_models:
            self.base_model = BertModel(self.base_model_type, self.activation, output_hidden_states=False)
        elif self.base_model_type == "CNN":
            self.base_model = CNN(self.activation)
        elif self.base_model_type == "BiLSTM":
            self.base_model = BiLSTM(self.activation)

        self.gender_encoder = LabelEncoder()
        self.education_encoder = LabelEncoder()
        self.race_encoder = LabelEncoder()
        self.emotion_encoder = LabelEncoder()
        
        # ModelCheckPoint Callback:
        cpkt = cpkt + "-{}-{}-{}".format(self.binary_loss, self.multiclass_loss, self.score_loss)
        cpkt = cpkt + "-epoch-{epoch:02d}-val-{}-loss-{val_score_output_loss:02f}.h5"
        checkpoint_filepath = "/content/gdrive/My Drive/WASSA-2021-Shared-Task/model-weights/"+ cpkt
        self.model_checkpoint_callback = ModelCheckpoint(filepath=checkpoint_filepath,
                                                    save_weights_only=True,
                                                    monitor='val_score_output_loss',
                                                    mode='auto',
                                                    save_freq = 'epoch',
                                                    save_best_only=True)

        # Reduce Learning Rate on Plateau Callback:
        self.reduce_lr_callback = ReduceLROnPlateau(monitor='val_score_output_loss', 
                                                    mode='auto',
                                                    factor=0.2, 
                                                    patience=10, 
                                                    min_lr=0.0005, 
                                                    verbose=1)
        # Early Stopping
        self.early_stopping = EarlyStopping(monitor='val_score_output_loss', 
                                            patience=20,
                                            verbose=1)





    # ------------------------------------------------------------ Function to prepare input for respective models ------------------------------------------------------------
    
    def prepare_input(self, utils_obj, corpus, maxlen=200, padding_type='post', truncating_type='post', mode="train"):
        if self.base_model_type in self.bert_models:
            return self.base_model.prepare_input(corpus, maxlen)
        else:
            return self.base_model.prepare_input(utils_obj, corpus, maxlen, padding_type, truncating_type, mode)





    # ------------------------------------------------------------ Funciton to prepare model outputs ------------------------------------------------------------
    
    def prepare_output(self, df, task="empathy", mode="train"):
        emotion = np.reshape(df.gold_emotion.values.tolist(), (len(df), 1))
        gender = np.reshape(df.gender.values.tolist(), (len(df), 1))
        education = np.reshape(df.education.values.tolist(), (len(df), 1))
        race = np.reshape(df.race.values.tolist(), (len(df), 1))
        
        if mode == "train":
            emotion = self.emotion_encoder.fit_transform(emotion)
            gender = self.gender_encoder.fit_transform(gender)
            education = self.education_encoder.fit_transform(education)
            race = self.race_encoder.fit_transform(race)
        elif mode == "dev" or "test":
            emotion = self.emotion_encoder.transform(emotion)
            gender = self.gender_encoder.transform(gender)
            education = self.education_encoder.transform(education)
            race = self.race_encoder.transform(race)

        if task == "empathy":
            score = np.reshape(df.gold_empathy.values.tolist(), (len(df), 1))
            bin = np.reshape(df.gold_empathy_bin.values.tolist(), (len(df), 1))
            return [bin, emotion, gender, education, race, score]
        if task == "distress":
            score = np.reshape(df.gold_distress.values.tolist(), (len(df), 1))
            bin = np.reshape(df.gold_distress_bin.values.tolist(), (len(df), 1))
            return [bin, emotion, gender, education, race, score]





    # ------------------------------------------------------------ Function to build the model ------------------------------------------------------------
    
    def build(self, embedding_matrix, input_length=100):
        if self.base_model_type in self.bert_models:
            input_ids = Input(shape=(input_length,))
            attention_mask = Input(shape=(input_length,))
            base_output = self.base_model.build(input_length)([input_ids, attention_mask])
        else:
            input = Input(shape=(input_length,))
            base_output = self.base_model.build(input_length, embedding_matrix)(input)

        x1 = Dense(32, self.activation, kernel_regularizer=l2(0.001))(base_output)
        bin = Dense(1, activation=self.binary_activation, name='bin_output')(x1)

        x2 = Dense(32, self.activation, kernel_regularizer=l2(0.001))(base_output)
        emotion = Dense(7, activation='softmax', name='emotion_output')(x2)

        x3 = Dense(32, self.activation, kernel_regularizer=l2(0.001))(base_output)
        gender = Dense(3, activation='softmax', name='gender_output')(x3)
        education = Dense(6, activation='softmax', name='education_output')(x3)
        race = Dense(6, activation='softmax', name='race_output')(x3)
        
        x = Concatenate(axis=1)([x1, x2, x3])
        x = Dense(16, self.activation)(x)
        score = Dense(1, name='score_output')(x)
        
        if self.base_model_type in self.bert_models:
            self.model = Model(inputs=[input_ids, attention_mask], 
                               outputs=[bin, emotion, gender, education, race, score])
        else:
            self.model = Model(inputs=input, 
                               outputs=[bin, emotion, gender, education, race, score])
        self.model.compile(optimizer=Adam(lr=0.001), 
                           loss={"bin_output":self.binary_loss,                                                           
                                 "emotion_output":self.multiclass_loss,
                                 "gender_output":self.multiclass_loss,
                                 "education_output":self.multiclass_loss,
                                 "race_output":self.multiclass_loss,
                                 "score_output":self.score_loss},
                           metrics={"score_output":self.score_metric})
        self.model.summary()





    # ------------------------------------------------------------ Function to plot model architecture ------------------------------------------------------------
        
    def plot_model_arch(self):
        return plot_model(self.model, show_shapes=True)





    # ------------------------------------------------------------ Function to train the model ------------------------------------------------------------
    
    def train(self, x_train, y_train, x_val, y_val, epochs=200, batch_size=32):
        history = self.model.fit(x_train,
                                 y_train, 
                                 epochs=epochs, 
                                 batch_size=batch_size, 
                                 verbose=1, 
                                 validation_data = (x_val, y_val),
                                 callbacks=[self.model_checkpoint_callback, self.reduce_lr_callback, self.early_stopping])
        return history





    # ------------------------------------------------------------ Function to predict model output ------------------------------------------------------------
    
    def prediction(self, val_essay, model_path=""):
        model_path = "/content/gdrive/My Drive/WASSA-2021-Shared-Task/model-weights/"+model_path
        self.model.load_weights(model_path)
        pred = self.model.predict(val_essay)
        return pred[-1]





    # ------------------------------------------------------------ Function to calculate the Pearson's correlation ------------------------------------------------------------
    
    def correlation(self, y_true, y_pred):
        y_pred = y_pred.flatten()
        y_true = y_true.flatten()
        return pearsonr(y_true, y_pred)
        
        
        
        
        
    # ------------------------------------------------------------ Function to plot model loss ------------------------------------------------------------
    
    def plot_curves(self, history):
        plt.plot(history.history['loss'])
        plt.plot(history.history['val_loss'])
        plt.title('model loss')
        plt.ylabel('loss')
        plt.xlabel('epoch')
        plt.legend(['train','validation'], loc='upper left')
        plt.show() 



        
        
        
        
        
