from unittest import TestCase


class TestSteemClientInit(TestCase):

    def test_initialization(self):
        pass

class TestStreamFreshPosts(TestCase):
    def test_post_with_correct_params_is_yielded(self):
        pass

    def test_non_main_post(self):
        pass

    def test_is_main_set(self):
        pass

    def test_post_time(self):
        pass

    def test_post_does_not_exist_exception(self):
        pass

    def test_lang_detect_exception(self):
        pass

    def test_general_exception(self):
        pass

class TestCommentOnPost(TestCase):

    def test_comment_on_post(self):
        pass

class TestPostSentiment(TestCase):

    def test_initialization(self):
        pass

    def test_tokens(self):
        pass

    def test_polarities(self):
        pass

    def test_normalized_polarities(self):
        pass

    def test_neg_polarity_sentence(self):
        pass

    def test_pos_polarity_sentence(self):
        pass

    def test_overall_polarity(self):
        pass

    def test_negative_polarity_description(self):
        pass

    def test_positive_polarity_description(self):
        pass

    def test_overall_polarity_description(self):
        pass

    def test_intro(self):
        pass

    def test_reason_for_posting(self):
        pass

    def test_description(self):
        pass

    def test_avg_normalized_polarity(self):
        pass

    def test_get_max_polarity(self):
        pass

    def test_to_csv(self):
        pass

    def test_is_neg_outlier(self):
        pass

    def test_is_pos_outlier(self):
        pass

def TestSteemStentimentCommenterRun(TestCase):
    pass

def TestSteemStentimentCommenterComment(TestCase):
    pass
