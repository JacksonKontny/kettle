import configparser
import datetime
import json
import random
import string
import time

import langdetect
from langdetect.lang_detect_exception import LangDetectException
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from nltk import tokenize
from pymongo import MongoClient
from steembase.exceptions import PostDoesNotExist
from steem import Steem
from steem.post import Post

config = configparser.ConfigParser()
config.read('config.ini')
POSTING_KEY = config['steem']['posting_key']
POSITIVE_THRESHOLD = float(config['steem']['positive_threshold'])
NEGATIVE_THRESHOLD = float(config['steem']['negative_threshold'])
ARTICLE_LENGTH_LOWER_LIMIT = int(config['steem'].get('article_length_lower_limit')) or 500
EXPIRATION_MINUTES = int(config['steem'].get('expiration_minutes')) or 15
ACCOUNT = config['steem']['account']
POST_CATEGORIES = set([
    'altcoin', 'bitshares', 'btc', 'business', 'crypto-news', 'curation',
    'esteem', 'happy', 'steemit', 'bitcoin', 'introduceyourself', 'cryptocurrency', 'steem',
    'blog', 'funny', 'news', 'dlive', 'dtube', 'dmania', 'crypto', 'money',
    'blockchain', 'technology', 'science', 'sports'
])
EXCLUDE_CATEGORIES = set(['nsfw'])
SPAM_DETECTORS = set(['badcontent'])


def convert_post_datetime(post_datetime_str):
    return datetime.datetime.strptime(
        post_datetime_str, "%Y-%m-%dT%H:%M:%S.000Z")

def datetime_filter(start_time, end_time=None):
    if not end_time:
        end_time = datetime.datetime.now()
    end_time = end_time + datetime.timedelta(hours=6)
    start_time = start_time + datetime.timedelta(hours=6)
    return {"created": {"$gte": start_time, "$lte": end_time}}

def vote_count_filter(vote_count):
    return {"$where": "this.active_votes.length > {}".format(vote_count)}

class SteemClient(object):
    def __init__(self, posting_key=POSTING_KEY, account=ACCOUNT):
        self.account = account
        self.steem = Steem(keys=[posting_key])

    def stream_fresh_posts(self, expiration_minutes=15):
        """
        Retrieves posts filtered by the input criteria.

        * Args
            * is_main -> boolean that designates if comments should be filtered out
            * allow_votes -> boolean that designates if posts that do not allow
                votes should be filtered out
            * expiration_minutes -> integer defining how old a post can be before
                filtering it out

        """
        stream = self.steem.stream_comments()
        while True:
            try:
                post = next(stream)
                if post.is_fresh_post:
                    yield post
            except PostDoesNotExist as exception:
                print('post does not exist exception... moving on')
            except LangDetectException as exception:
                try:
                    print('language in post not understood')
                except:
                    print('couldnt even print out post body')
            except Exception as e:
                print(e)
                stream = self.steem.stream_comments()

    def is_fresh_post(self, post):
        return (
            not post.is_main_post()
            and post.allow_votes
            and post.time_elapsed() < datetime.timedelta(
                minutes=EXPIRATION_MINUTES
            ) and langdetect.detect(post.body) == 'en'
            and post.category not in EXCLUDE_CATEGORIES
            and len(post.body.split(' ')) > ARTICLE_LENGTH_LOWER_LIMIT
        )


    def comment_on_post(self, post, comment):
        try:
            post.reply(author=self.account, body=comment, title=self.account)
            time.sleep(20)
        except Exception as e:
            print(e)

    def upvote_post(self, post):
        try:
            post.upvote(voter=self.account)
        except Exception as e:
            print(e)

    def write_post(self, title, body, tags):
        self.steem.commit.post(
            author=self.account,
            body=body,
            tags=tags,
            title=title,
        )

    def is_post_valid(self, post):
        return not is_post_spam(post)

    def is_post_spam(self, post):
        replies = post.get_replies()
        for reply in replies:
            if reply.author in SPAM_DETECTORS:
                return True
        return False


class MongoSteem(object):

    def __init__(self, host='localhost', port=27017, db_name='steem'):
        self.host = host
        self.port = port
        self.db_name = db_name
        self.init_collections()

    def init_collections(self):
        mongo_client = MongoClient(self.host, self.port)
        db = getattr(mongo_client, self.db_name)
        self.posts = db.posts
        self.users = db.users

    def get_post_data_for_storage(self, post):
        try:
            export = post.export()
        except Exception as e:
            print(e)

        export['tags'] = list(export['tags'])
        return export

    def store_post(self, post, additional_data=None):
        post_data = self.get_post_data_for_storage(post)
        if additional_data:
            post_data.update(additional_data)
        try:
            self.posts.insert_one(post_data)
        except:
            print('failed to store post, reinitting db and trying again')
            self.init_collections()
            self.store_post(post, additional_data)

    def stream_posts_from_mongo(self, query=None, limit=None, raw=False):
        if query is None:
            query = {}
        post_query = self.posts.find(query)
        if limit:
            post_query = post_query.limit(limit)
        try:
            for post_data in post_query:
                if raw:
                    yield post_data
                else:
                    yield Post(post_data)

        except Exception as e:
            print(e)

    def update_post(self, post, **kwargs):
        post.refresh()
        post_data = self.get_post_data_for_storage(post)
        post_data.update(kwargs)
        try:
            self.posts.update_one(
                {'identifier': post.identifier},
                {'$set': post_data},
            )
        except:
            print('failed to update post, reinitting db and trying again')
            self.init_collections()
            self.update_post(post, **kwargs)

    def update_posts(self, query=None):
        if not query:
            query = {}
        for post in self.stream_posts_from_mongo(query=query):
            self.update_post(post)

    def is_post_new(self, post):
        try:
            return not bool(self.posts.find_one({'id': post.id}, {'_id': 1}))
        except:
            print('failed to check if post is new, reinitting db and trying again')
            self.init_collection()
            return self.is_post_new(post)

    def unsubscribe_user(self, user):
        self.users.update_one(
            {'user': user},
            {'$set': {'user': user, 'unsubscribed': True}},
            upsert=True,
        )

    def get_positive_posts(self):
        return self.posts.find({
            'created': {'$gt': datetime.datetime.now() - datetime.timedelta(hours=48)},
            'is_pos_outlier': True,
            'is_in_positive_article_post': {'$exists': False},
        })

    def is_post_valid(self, post):
        return self.is_post_new(post) and self.is_user_unsubscribed(post.author)

    def is_user_unsubscribed(self, user):
        return bool(
            self.users.find_one(
                {
                    'unsubscribed': True,
                    'user': user
                },
                {'_id': 1}
            )
        )


class PostSentimentAnalyzer(object):
    def __init__(self):
        self.sid = SentimentIntensityAnalyzer()
        self.negative_threshold = NEGATIVE_THRESHOLD
        self.positive_threshold = POSITIVE_THRESHOLD

    def get_tokens(self, post):
        return tokenize.sent_tokenize(post.body)

    def get_polarities(self, post):
        polarities = []
        for token in self.get_tokens(post):
            polarities.append(self.sid.polarity_scores(token))
        return polarities

    def get_normalized_polarities(self, post):
        return [pol['pos'] - pol['neg'] for pol in self.get_polarities(post)]

    def get_overall_polarity(self, post):
        overall_polarity = {}
        polarities = self.get_polarities(post)
        for key in ['pos', 'neg', 'neu', 'compound']:
            average = round(
                sum([pol[key] for pol in polarities]) / len(polarities),
                3
            )
            overall_polarity[key] = average
        return overall_polarity

    def get_intro(self, post):
        return (
            'Thanks for the post, {post_author}.\n\n'
            'This bot runs through hundreds of posts per day selecting a small '
            'percentage of posts that have exceptional positivity.\n\n'.format(
                post_author=post.author
            )
        )

    @property
    def reason_for_posting(self):
        return (
            'Your post has been selected and upvoted because it has a high '
            'concentration of positive words that give feel-good vibes. '
            'Thank you for creating content that focuses on the bright side.\n\n'
        )

    @property
    def vote_comment(self):
        return (
            'Please comment \'yes\' if you think this post is a positive post or '
            '\'no\' if you feel that this post is not a positive post. '
            'Articles with the most \'yes\' votes will be included in a daily roundup '
            'of positive posts.\n\n'
            'You may comment \"stop\" to be added to a list of users that will '
            'never be included and will receive no more comments.\n\n'
        )

    def get_description(self, post):
        return '{}{}{}'.format(
            self.get_intro(post),
            self.reason_for_posting,
            self.vote_comment,
        )

    def get_avg_normalized_polarity(self, post):
        normalized_polarities = self.get_normalized_polarities(post)
        return round(
            sum(normalized_polarities) / len(normalized_polarities),
            2
        )

    def to_mongo(self, post):
        return {
            'polarities': self.get_polarities(post),
            'normalized_polarities': self.get_normalized_polarities(post),
            'overall_polarity': self.get_overall_polarity(post),
            'is_pos_outlier': self.is_pos_outlier(post),
            'is_neg_outlier': self.is_neg_outlier(post),
        }

    def is_neg_outlier(self, post):
        return self.get_avg_normalized_polarity(post) <= self.negative_threshold

    def is_pos_outlier(self, post):
        return self.get_avg_normalized_polarity(post) >= self.positive_threshold


class SteemSentimentCommenter(object):
    def __init__(self):
        self.steem_client = SteemClient()
        self.mongo_steem = MongoSteem()
        self.post_cooldown = False
        self.sentiment_analyzer = PostSentimentAnalyzer()

    def run(self):
        for post in self.steem_client.stream_fresh_posts():
            if datetime.datetime.now().hour != 13 and self.post_cooldown:
                self.post_cooldown = False
            if self.is_post_valid(post):
                self.save_sentiment(post)
                if self.sentiment_analyzer.is_pos_outlier(post):
                    self.handle_interaction_with_content_provider(post)
            if datetime.datetime.now().hour == 13 and not self.post_cooldown:
                self.write_positive_article_post()
                self.post_cooldown = True

    def is_post_valid(self, post):
        return (
            self.mongo_steem.is_post_valid(post)
            and self.steem_client.is_post_valid(post)
        )

    def save_sentiment(self, post):
        self.mongo_steem.store_post(
            post,
            additional_data=self.sentiment_analyzer.to_mongo(post)
        )

    def handle_interaction_with_content_provider(self, post):
        post.refresh()
        self.steem_client.upvote_post(post)
        description = self.sentiment_analyzer.get_description(post)
        self.steem_client.comment_on_post(post, description)

    def get_steemit_url(self, post):
        if isinstance(post, Post):
            post_url = post.url
        else:
            post_url = post['url']
        return 'https://steemit.com{}'.format(post_url)

    def write_positive_article_post(self):
        title = 'Top positive articles of the day - {}'.format(str(datetime.date.today()))
        intro = (
            "Below are the top uplifting posts of the day.  These posts have "
            "been selected due to their overwhelming positive word choice. The "
            "articles listed have more positive words than 99.5% of articles "
            "posted in english on the steemit platform.  Go ahead and give these "
            "articles a read and see if they can improve your life, inspire you and improve "
            "your day:\n\n"
        )
        positive_posts = self.mongo_steem.get_positive_posts()
        verified_posts = []
        for post_data in positive_posts:
            post = Post(post_data)
            if self.is_post_verified_positive(post):
                verified_posts.append(post)
                self.mongo_steem.update_post(post, is_in_positive_article_post=True)
        links = '\n\n'.join([self.get_steemit_url(post) for post in verified_posts])
        authors = ', '.join(['@' + post.author for post in verified_posts])
        author_thank_you = (
            'Thanks to the authors for creating the content:\n{}\n\n'.format(
                authors
            )
        )
        curators = self.get_post_curators(verified_posts)
        curator_thank_you = (
            'And a very special thanks to the curators that helped ensure this '
            'content is legitimate: {}'.format(', '.join(curators))
        )
        body = '{}{}\n\n{}{}'.format(intro, links, author_thank_you, curator_thank_you)
        tags = ['life', 'motivation', 'inspiration', 'happy', 'good-karma']
        if len(links) >= 3:
            print('posting: {}'.format(title))
            self.steem_client.write_post(title, body, tags)

    def get_post_curators(self, verified_posts):
        post_curators = set()
        for post in verified_posts:
            sentiment_bot_comment = self.get_senti_bot_comment(post)
            post_curators = post_curators.union(
                set(['@' + comment['voter'] for comment in sentiment_bot_comment.active_votes])
            )
            for sentiment_bot_reply in sentiment_bot_comment.get_replies():
                table = str.maketrans(dict.fromkeys(string.punctuation))
                reply_words = set(sentiment_bot_reply.body.translate(table).lower().split(' '))
                if 'yes' in reply_words or 'no' in reply_words:
                    post_curators.add('@' + sentiment_bot_reply.author)
        return post_curators

    def get_senti_bot_comment(self, post):
        for reply in post.get_replies():
            if reply.author == self.steem_client.account:
                return reply

    def is_post_verified_positive(self, post):
        sentiment_bot_comment = self.get_senti_bot_comment(post)
        if sentiment_bot_comment.net_votes > 0:
            return True
        no_count = 0
        yes_count = 0
        for sentiment_bot_reply in sentiment_bot_comment.get_replies():
            table = str.maketrans(dict.fromkeys(string.punctuation))
            reply_words = set(sentiment_bot_reply.body.translate(table).lower().split(' '))
            if 'stop' in reply_words:
                if post.author == sentiment_bot_reply.author:
                    self.mongo_steem.unsubscribe_user(post.author)
                    self.steem_client.comment_on_post(
                        sentiment_bot_reply,
                        (
                            'Sorry for the trouble {}, you have been removed.'.format(post.author)
                        )
                    )
                    return False
                else:
                    self.steem_client.comment_on_post(
                        sentiment_bot_reply,
                        (
                            'Sorry, only {} can unsubscribe.'.format(post.author)
                        )
                    )
            if 'yes' in reply_words:
                yes_count += 1 + sentiment_bot_reply.net_votes
            if 'no' in reply_words:
                no_count += 1 + sentiment_bot_reply.net_votes
        return yes_count > no_count


def run_commenter():
    try:
        commenter = SteemSentimentCommenter()
        commenter.run()
    except KeyboardInterrupt:
        print('time to exit')
    except Exception as e:
        print('The whole thing failed!')
        print(e)
        run_commenter()

if __name__ == '__main__':
    run_commenter()
