import pygame
pygame.mixer.init()

pygame.mixer.music.load("alert.wav")
pygame.mixer.music.play()

input("Press Enter to exit...")